#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Графический интерфейс анализатора метрики граничных значений
для исходного кода на Ruby (tkinter, без внешних зависимостей).

Запуск:
    python3 boundary_gui.py
"""
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import boundary_core

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE_PATH = os.path.join(HERE, "tests", "analyzed.rb")

FALLBACK_SAMPLE = '''n = 5
sum = 0
i = 1
while i <= n
  sum += i
  i += 1
end
if sum > 10
  puts "много"
else
  puts "мало"
end
'''

KIND_NAMES = {"start": "начало", "end": "конец", "proc": "действие",
              "cond": "условие", "io": "ввод/вывод", "loop": "цикл loop"}


class BoundaryApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Метрика граничных значений — анализатор кода Ruby")
        self.geometry("1280x780")
        self.minsize(1000, 620)
        self.result = None
        self._build_toolbar()
        self._build_body()

    # ---------------------------------------------------------- интерфейс
    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(side=tk.TOP, fill=tk.X)
        for text, cmd in (("Открыть .rb файл…", self.on_open),
                          ("Анализировать", self.on_analyze),
                          ("Загрузить пример", self.on_sample),
                          ("Экспорт схемы (.dot)", self.on_export),
                          ("Очистить", self.on_clear)):
            ttk.Button(bar, text=text, command=cmd).pack(side=tk.LEFT, padx=(0, 6))
        self.file_label = ttk.Label(bar, text="Файл не выбран", foreground="#5B6472")
        self.file_label.pack(side=tk.LEFT, padx=(8, 0))

    def _build_body(self):
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        left = ttk.Frame(paned)
        ttk.Label(left, text="Исходный код Ruby").pack(anchor=tk.W, pady=(0, 4))
        wrap = ttk.Frame(left); wrap.pack(fill=tk.BOTH, expand=True)
        self.source = tk.Text(wrap, wrap=tk.NONE, undo=True,
                              font=("Menlo", 12) if os.name != "nt" else ("Consolas", 11))
        ys = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=self.source.yview)
        xs = ttk.Scrollbar(left, orient=tk.HORIZONTAL, command=self.source.xview)
        self.source.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.source.grid(row=0, column=0, sticky="nsew"); ys.grid(row=0, column=1, sticky="ns")
        wrap.rowconfigure(0, weight=1); wrap.columnconfigure(0, weight=1)
        xs.pack(fill=tk.X)
        paned.add(left, weight=2)

        right = ttk.Frame(paned)
        ttk.Label(right, text="Результат — метрика граничных значений",
                  font=("Helvetica", 11, "bold")).pack(anchor=tk.W, pady=(0, 8))
        cards = ttk.Frame(right); cards.pack(fill=tk.X)
        self.sa_var = tk.StringVar(value="0")
        self.so_var = tk.StringVar(value="0.000")
        self.v_var = tk.StringVar(value="0")
        self.formula_var = tk.StringVar(value="So = 1 − (v − 1) / Sa = —")
        self._card(cards, 0, "Абсолютная граничная\nсложность Sa", self.sa_var)
        self._card(cards, 1, "Относительная граничная\nсложность So", self.so_var)
        self._card(cards, 2, "Число вершин\nграфа v", self.v_var)
        for c in range(3):
            cards.columnconfigure(c, weight=1)
        ttk.Label(right, textvariable=self.formula_var, foreground="#5B6472").pack(anchor=tk.W, pady=(8, 8))

        nb = ttk.Notebook(right); nb.pack(fill=tk.BOTH, expand=True)
        self.tree_v = self._tree(nb, "Скорректированные сложности вершин",
                                 (("id", "Вершина", 80), ("kind", "Тип", 95),
                                  ("text", "Оператор", 250), ("deg", "Исх. степень", 100),
                                  ("role", "Роль", 130), ("s", "Сложность", 90)))
        self.tree_s = self._tree(nb, "Подграфы вершин выбора",
                                 (("id", "Вершина выбора", 100), ("tr", "Вершины перехода", 120),
                                  ("sub", "Вершины подграфа", 300), ("low", "Нижняя граница", 110),
                                  ("s", "Скорр. сложность", 120)))
        self.tree_b = self._tree(nb, "Блоки схемы алгоритма",
                                 (("id", "№", 50), ("kind", "Тип", 100), ("text", "Оператор", 380),
                                  ("to", "Переходы", 260)))
        paned.add(right, weight=3)

    def _card(self, parent, col, title, var):
        card = ttk.Frame(parent, relief=tk.RIDGE, borderwidth=1, padding=10)
        card.grid(row=0, column=col, sticky="nsew", padx=4)
        ttk.Label(card, text=title, foreground="#5B6472", justify=tk.CENTER).pack()
        ttk.Label(card, textvariable=var, font=("Helvetica", 26, "bold")).pack(pady=(4, 0))

    def _tree(self, nb, title, cols):
        frame = ttk.Frame(nb)
        nb.add(frame, text=title)
        tree = ttk.Treeview(frame, columns=[c[0] for c in cols], show="headings")
        for key, head, width in cols:
            tree.heading(key, text=head)
            tree.column(key, width=width, anchor=tk.W if key in ("text", "sub", "to") else tk.CENTER)
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); sb.pack(side=tk.RIGHT, fill=tk.Y)
        return tree

    # ---------------------------------------------------------- обработчики
    def on_open(self):
        path = filedialog.askopenfilename(title="Выберите файл Ruby",
                                          filetypes=[("Ruby", "*.rb"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                code = f.read()
        except OSError as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть файл:\n{e}")
            return
        self._set_source(code)
        self.file_label.config(text="Файл: " + os.path.basename(path))
        self.analyze()

    def on_sample(self):
        try:
            with open(SAMPLE_PATH, "r", encoding="utf-8") as f:
                code = f.read()
            name = "tests/analyzed.rb"
        except OSError:
            code, name = FALLBACK_SAMPLE, "встроенный пример"
        self._set_source(code)
        self.file_label.config(text="Загружен пример: " + name)
        self.analyze()

    def on_analyze(self):
        self.analyze()

    def on_export(self):
        if self.result is None:
            messagebox.showinfo("Экспорт", "Сначала выполните анализ.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".dot",
                                            filetypes=[("Graphviz DOT", "*.dot")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(boundary_core.to_dot(self.result))

    def on_clear(self):
        self._set_source("")
        self.file_label.config(text="Файл не выбран")
        self.result = None
        self.sa_var.set("0"); self.so_var.set("0.000"); self.v_var.set("0")
        self.formula_var.set("So = 1 − (v − 1) / Sa = —")
        for t in (self.tree_v, self.tree_s, self.tree_b):
            t.delete(*t.get_children())

    def _set_source(self, code):
        self.source.delete("1.0", tk.END)
        self.source.insert("1.0", code)

    def analyze(self):
        code = self.source.get("1.0", tk.END)
        if not code.strip():
            messagebox.showinfo("Анализ", "Введите или загрузите код Ruby.")
            return
        try:
            r = boundary_core.analyze(code)
        except Exception as e:  # некорректный код
            messagebox.showerror("Ошибка анализа", str(e))
            return
        self.result = r
        self.sa_var.set(str(r.sa))
        self.so_var.set(f"{r.so:.3f}")
        self.v_var.set(str(r.v))
        self.formula_var.set(f"So = 1 − (v − 1) / Sa = 1 − ({r.v} − 1) / {r.sa} = {r.so:.3f}")

        for t in (self.tree_v, self.tree_s, self.tree_b):
            t.delete(*t.get_children())
        for v in r.vertices:
            outs = r.out_edges(v.id)
            role = "вершина выбора" if v.id in r.selection else ("конечная" if v.kind == "end" else "принимающая")
            self.tree_v.insert("", tk.END, values=(v.id, KIND_NAMES[v.kind], v.text, len(outs),
                                                   role, r.complexity[v.id]))
            to = ", ".join(f"{b}" + (f" ({l})" if l else "") for b, l in outs) or "—"
            self.tree_b.insert("", tk.END, values=(v.id, KIND_NAMES[v.kind], v.text, to))
        for vid, s in r.selection.items():
            self.tree_s.insert("", tk.END, values=(vid, ", ".join(map(str, s.transitions)),
                                                   ", ".join(map(str, s.subgraph)),
                                                   s.lower if s.lower is not None else "—", s.complexity))


if __name__ == "__main__":
    BoundaryApp().mainloop()
