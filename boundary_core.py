#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ядро анализатора метрики граничных значений для исходного кода на Ruby.

Модуль не зависит от GUI и может запускаться из командной строки:

    python3 boundary_core.py <файл.rb> [--dot схема.dot]

------------------------------------------------------------------------
АЛГОРИТМ
------------------------------------------------------------------------
1. Исходный текст Ruby разбирается в дерево операторов, затем строится
   детализированная схема алгоритма (ГОСТ 19.701-90) как ориентированный
   граф G = (V, E): ОДНОМУ ОПЕРАТОРУ СООТВЕТСТВУЕТ ОДНА ВЕРШИНА.
     * while / until / for / loop / итераторы (each, times, ...) -> циклы;
       у for и итераторов явно строятся инициализация переменной цикла,
       проверка условия и изменение переменной цикла;
     * if / elsif / else / unless и модификаторы (x if c, x unless c)
       -> вершины-условия;
     * case/when -> вложенные друг в друга условия;
     * break / next / return -> отдельные вершины-операторы;
     * puts / print / p -> вершины вывода, gets -> вершины ввода.
   Номера вершин идут в порядке следования операторов в тексте;
   вершина 1 — «Начало», последняя — «Конец».

2. Метрика граничных значений:
     * положительная степень вершины = число исходящих дуг;
       вершины со степенью <= 1 — принимающие, >= 2 — вершины выбора;
     * граф разбивается на максимальное число подграфов: вход в подграф
       только через вершину выбора, у подграфа есть нижняя граница —
       вершина, в которую можно попасть из любой другой вершины подграфа
       (ближайший общий постдоминатор вершины выбора);
     * скорректированная сложность вершины выбора = число вершин её
       подграфа (включая нижнюю границу; саму вершину выбора — только если
       она лежит на цикле подграфа);
     * скорректированная сложность принимающей вершины = 1,
       конечной вершины = 0;
     * Sa = сумма скорректированных сложностей всех вершин;
     * So = 1 - (v - 1) / Sa, где v — число вершин графа.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 1. Подготовка текста
# ---------------------------------------------------------------------------


def _clean_line(line: str) -> Tuple[str, str]:
    """Возвращает (код без комментария, код с «замаскированными» строками).
    В маске содержимое строковых литералов заменено пробелами — по ней ищутся
    ключевые слова, чтобы слова внутри строк не принимались за операторы."""
    code, mask = [], []
    quote: Optional[str] = None
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if quote:
            if ch == "\\" and i + 1 < n:
                code.append(line[i:i + 2]); mask.append("  "); i += 2; continue
            code.append(ch)
            if ch == quote:
                quote = None; mask.append(ch)
            else:
                mask.append(" ")
            i += 1; continue
        if ch in "\"'":
            quote = ch; code.append(ch); mask.append(ch); i += 1; continue
        if ch == "#":
            break
        code.append(ch); mask.append(ch); i += 1
    return "".join(code).rstrip(), "".join(mask).rstrip()


def prepare(source: str) -> List[Tuple[str, str]]:
    lines: List[Tuple[str, str]] = []
    in_block_comment = False
    for raw in source.splitlines():
        s = raw.strip()
        if s.startswith("=begin"):
            in_block_comment = True; continue
        if s.startswith("=end"):
            in_block_comment = False; continue
        if in_block_comment:
            continue
        code, mask = _clean_line(raw)
        code, mask = code.strip(), mask.strip()
        if code.endswith(";"):
            code, mask = code[:-1].rstrip(), mask[:-1].rstrip()
        if code:
            lines.append((code, mask))
    return lines


# ---------------------------------------------------------------------------
# 2. Разбор в дерево операторов
# ---------------------------------------------------------------------------

ITER_METHODS = ("each_with_index", "each_with_object", "each_pair", "each_key",
                "each_value", "each_char", "each_line", "each_slice",
                "each_cons", "each", "times", "upto", "downto", "step",
                "map", "collect", "select", "filter", "reject", "detect",
                "find_all", "flat_map", "inject", "reduce", "cycle")

RE_IF = re.compile(r"^if\s+(.+)$")
RE_UNLESS = re.compile(r"^unless\s+(.+)$")
RE_WHILE = re.compile(r"^while\s+(.+?)(\s+do)?$")
RE_UNTIL = re.compile(r"^until\s+(.+?)(\s+do)?$")
RE_FOR = re.compile(r"^for\s+([\w\s,]+?)\s+in\s+(.+?)(\s+do)?$")
RE_LOOP = re.compile(r"^loop\s+do(\s*\|.*\|)?$")
RE_ITER = re.compile(r"^(.+?)\.(%s)(\(.*\))?\s+do(\s*\|(.*)\|)?$" % "|".join(ITER_METHODS))
RE_DOBLOCK = re.compile(r"^.+\s+do(\s*\|.*\|)?$")
RE_CASE = re.compile(r"^case(\s+(.+))?$")
RE_MOD = re.compile(r"^(.*\S)\s+(if|unless|while|until)\s+(.+)$")
RE_JUMP = re.compile(r"^(break|next|redo|return)\b(.*)$")
RE_OPENER = re.compile(r"^(def|class|module|begin)\b")


@dataclass
class Stmt:
    kind: str                      # simple/if/unless/while/until/for/loop/iter/case/jump/modif
    text: str = ""
    cond: str = ""
    body: List["Stmt"] = field(default_factory=list)
    branches: List[Tuple[str, List["Stmt"]]] = field(default_factory=list)  # if/elsif, when
    else_body: Optional[List["Stmt"]] = None
    extra: dict = field(default_factory=dict)
    inner: Optional["Stmt"] = None  # для модификаторов


class Parser:
    def __init__(self, lines: List[Tuple[str, str]]):
        self.L = lines
        self.i = 0

    def peek(self):
        return self.L[self.i] if self.i < len(self.L) else None

    def parse(self, stops: Tuple[str, ...] = ()) -> List[Stmt]:
        out: List[Stmt] = []
        while self.i < len(self.L):
            code, mask = self.L[self.i]
            word = mask.split(None, 1)[0] if mask else ""
            if word in stops or mask in stops:
                break
            if mask == "end":      # лишний end (например, закрытие def)
                break
            out.extend(self.statement())
        return out

    # --- вспомогательное
    def _take_end(self):
        if self.i < len(self.L) and self.L[self.i][1] == "end":
            self.i += 1

    def statement(self) -> List[Stmt]:
        code, mask = self.L[self.i]
        # def/class/module/begin — «прозрачны»: тело разбирается как обычные операторы
        if RE_OPENER.match(mask):
            self.i += 1
            body = self.parse(("end",))
            self._take_end()
            return body
        m = RE_WHILE.match(mask)
        if m:
            self.i += 1
            body = self.parse(("end",)); self._take_end()
            return [Stmt("while", cond=code[m.start(1):m.end(1)], body=body)]
        m = RE_UNTIL.match(mask)
        if m:
            self.i += 1
            body = self.parse(("end",)); self._take_end()
            return [Stmt("until", cond=code[m.start(1):m.end(1)], body=body)]
        m = RE_FOR.match(mask)
        if m:
            self.i += 1
            body = self.parse(("end",)); self._take_end()
            return [Stmt("for", cond=code[m.start(2):m.end(2)], body=body,
                         extra={"var": code[m.start(1):m.end(1)].strip()})]
        if RE_LOOP.match(mask):
            self.i += 1
            body = self.parse(("end",)); self._take_end()
            return [Stmt("loop", body=body)]
        m = RE_ITER.match(mask)
        if m:
            recv = code[m.start(1):m.end(1)]
            meth = m.group(2)
            args = code[m.start(3):m.end(3)] if m.group(3) else ""
            var = (code[m.start(5):m.end(5)] if m.group(5) is not None else "").strip() or "_"
            self.i += 1
            body = self.parse(("end",)); self._take_end()
            return [Stmt("iter", body=body, extra={"recv": recv, "meth": meth, "var": var, "args": args})]
        m = RE_IF.match(mask)
        if m:
            return [self._if_like("if", code, m)]
        m = RE_UNLESS.match(mask)
        if m:
            return [self._if_like("unless", code, m)]
        m = RE_CASE.match(mask)
        if m and not RE_MOD.match(mask):
            return [self._case(code, m)]
        # произвольный блок с do ... end (например File.open(...) do |f|)
        if RE_DOBLOCK.match(mask) and not RE_MOD.match(mask):
            self.i += 1
            body = self.parse(("end",)); self._take_end()
            return [Stmt("simple", text=code)] + body
        # простой оператор, возможно с модификатором
        self.i += 1
        m = RE_MOD.match(mask)
        if m:
            inner = self._simple(code[m.start(1):m.end(1)])
            return [Stmt("modif", cond=code[m.start(3):m.end(3)], inner=inner,
                         extra={"kw": m.group(2)})]
        return [self._simple(code)]

    def _simple(self, text: str) -> Stmt:
        m = RE_JUMP.match(text)
        if m:
            return Stmt("jump", text=text, extra={"kw": m.group(1)})
        return Stmt("simple", text=text)

    def _if_like(self, kw: str, code: str, m) -> Stmt:
        cond = code[m.start(1):m.end(1)]
        cond = re.sub(r"\s+then$", "", cond)
        self.i += 1
        node = Stmt(kw)
        cur_cond = cond
        while True:
            body = self.parse(("elsif", "else", "end"))
            node.branches.append((cur_cond, body))
            if self.i >= len(self.L):
                break
            c, mk = self.L[self.i]
            if mk.startswith("elsif"):
                cur_cond = re.sub(r"\s+then$", "", c[len("elsif"):].strip())
                self.i += 1
                continue
            if mk == "else":
                self.i += 1
                node.else_body = self.parse(("end",))
            break
        self._take_end()
        return node

    def _case(self, code: str, m) -> Stmt:
        subject = (code[m.start(2):m.end(2)] if m.group(2) else "").strip()
        self.i += 1
        node = Stmt("case", cond=subject)
        while self.i < len(self.L):
            c, mk = self.L[self.i]
            if mk.startswith("when"):
                conds = re.sub(r"\s+then$", "", c[len("when"):].strip())
                self.i += 1
                body = self.parse(("when", "else", "end"))
                node.branches.append((conds, body))
            elif mk == "else":
                self.i += 1
                node.else_body = self.parse(("end",))
            else:
                break
        self._take_end()
        return node


# ---------------------------------------------------------------------------
# 3. Построение графа схемы алгоритма
# ---------------------------------------------------------------------------

# типы вершин: start, end, proc, cond, io, loop
@dataclass
class Vertex:
    id: int
    kind: str
    text: str


Pending = List[Tuple[int, str]]


def _aug(text: str) -> str:
    """a += b  ->  a = a + b"""
    m = re.match(r"^(.+?)\s*(\+|-|\*|/|%|\*\*|\|\||&&)=\s*(.+)$", text)
    if m and not re.match(r"^\s*[=!<>]", text):
        lhs, op, rhs = m.group(1).strip(), m.group(2), m.group(3).strip()
        return f"{lhs} = {lhs} {op} {rhs}"
    return text


def _io(text: str) -> Tuple[str, str]:
    m = re.match(r"^(puts|print|p|pp)\b\s*\(?(.*?)\)?$", text)
    if m:
        return "io", "вывод: " + (m.group(2) or "").strip()
    if re.search(r"\bgets\b", text):
        var = text.split("=")[0].strip() if "=" in text else ""
        return "io", "ввод: " + var if var else "ввод"
    return "proc", _aug(text)


class Builder:
    def __init__(self):
        self.V: List[Vertex] = []
        self.E: List[Tuple[int, int, str]] = []
        self.loops: List[dict] = []
        self.returns: Pending = []

    def node(self, kind: str, text: str) -> int:
        v = Vertex(len(self.V) + 1, kind, text)
        self.V.append(v)
        return v.id

    def connect(self, pend: Pending, target: int):
        for a, lab in pend:
            self.E.append((a, target, lab))

    # --- последовательность
    def seq(self, stmts: List[Stmt], pend: Pending) -> Pending:
        for s in stmts:
            pend = self.stmt(s, pend)
        return pend

    def new_loop(self) -> dict:
        ctx = {"breaks": [], "nexts": []}
        self.loops.append(ctx)
        return ctx

    def stmt(self, s: Stmt, pend: Pending) -> Pending:
        k = s.kind
        if k == "simple":
            kind, txt = _io(s.text)
            n = self.node(kind, txt); self.connect(pend, n)
            return [(n, "")]
        if k == "jump":
            return self.jump(s, pend)
        if k == "modif":
            return self.modifier(s, pend)
        if k == "if" or k == "unless":
            return self.if_chain(s, pend)
        if k == "case":
            return self.case(s, pend)
        if k == "while":
            return self.while_loop(s.cond, s.body, pend, until=False)
        if k == "until":
            return self.while_loop(s.cond, s.body, pend, until=True)
        if k == "for":
            return self.for_loop(s, pend)
        if k == "loop":
            return self.loop(s, pend)
        if k == "iter":
            return self.iter_loop(s, pend)
        raise ValueError(k)

    # --- переходы
    def jump(self, s: Stmt, pend: Pending) -> Pending:
        n = self.node("proc", s.text); self.connect(pend, n)
        kw = s.extra["kw"]
        if kw == "break" and self.loops:
            self.loops[-1]["breaks"].append((n, ""))
        elif kw in ("next", "redo") and self.loops:
            self.loops[-1]["nexts"].append((n, ""))
        else:
            self.returns.append((n, ""))
        return []

    # --- модификаторы: X if c / X unless c / X while c / X until c
    def modifier(self, s: Stmt, pend: Pending) -> Pending:
        kw = s.extra["kw"]
        if kw in ("while", "until"):
            return self.while_loop(s.cond, [s.inner], pend, until=(kw == "until"))
        d = self.node("cond", s.cond + " ?"); self.connect(pend, d)
        body_label, skip_label = ("да", "нет") if kw == "if" else ("нет", "да")
        out = self.stmt(s.inner, [(d, body_label)])
        return out + [(d, skip_label)]

    # --- if / elsif / else, unless
    def if_chain(self, s: Stmt, pend: Pending) -> Pending:
        outs: Pending = []
        first = True
        for idx, (cond, body) in enumerate(s.branches):
            d = self.node("cond", cond + " ?"); self.connect(pend, d)
            yes, no = ("да", "нет")
            if s.kind == "unless" and idx == 0:
                yes, no = ("нет", "да")
            outs += self.seq(body, [(d, yes)])
            pend = [(d, no)]
        if s.else_body is not None:
            outs += self.seq(s.else_body, pend)
        else:
            outs += pend
        return outs

    # --- case / when -> вложенные условия
    def case(self, s: Stmt, pend: Pending) -> Pending:
        outs: Pending = []
        for conds, body in s.branches:
            d = self.node("cond", self.when_text(s.cond, conds) + " ?"); self.connect(pend, d)
            outs += self.seq(body, [(d, "да")])
            pend = [(d, "нет")]
        if s.else_body is not None:
            outs += self.seq(s.else_body, pend)
        else:
            outs += pend
        return outs

    @staticmethod
    def when_text(subject: str, conds: str) -> str:
        if not subject:
            return conds
        parts = [p.strip() for p in conds.split(",") if p.strip()]
        res = []
        for p in parts:
            if ".." in p:
                res.append(f"{subject} in {p}")
            else:
                res.append(f"{subject} == {p}")
        return " || ".join(res)

    # --- циклы
    def while_loop(self, cond: str, body: List[Stmt], pend: Pending, until: bool) -> Pending:
        d = self.node("cond", cond + " ?"); self.connect(pend, d)
        ctx = self.new_loop()
        enter, leave = ("нет", "да") if until else ("да", "нет")
        out = self.seq(body, [(d, enter)])
        self.connect(out + ctx["nexts"], d)
        self.loops.pop()
        return [(d, leave)] + ctx["breaks"]

    def _counted(self, init: str, cond: str, inc: str, body: List[Stmt], pend: Pending) -> Pending:
        i = self.node("proc", init); self.connect(pend, i)
        d = self.node("cond", cond + " ?"); self.connect([(i, "")], d)
        ctx = self.new_loop()
        out = self.seq(body, [(d, "да")])
        n = self.node("proc", inc)
        self.connect(out + ctx["nexts"], n)
        self.connect([(n, "")], d)
        self.loops.pop()
        return [(d, "нет")] + ctx["breaks"]

    def for_loop(self, s: Stmt, pend: Pending) -> Pending:
        var, coll = s.extra["var"], s.cond.strip()
        m = re.match(r"^\(?\s*(.+?)\s*(\.\.\.?)\s*(.+?)\s*\)?$", coll)
        if m:
            lo, op, hi = m.groups()
            cmp = "<" if op == "..." else "<="
            return self._counted(f"{var} = {lo}", f"{var} {cmp} {hi}", f"{var} = {var} + 1", s.body, pend)
        return self._counted(f"{var} = первый элемент {coll}", f"в {coll} остались элементы",
                             f"{var} = следующий элемент {coll}", s.body, pend)

    def iter_loop(self, s: Stmt, pend: Pending) -> Pending:
        recv, meth, var = s.extra["recv"], s.extra["meth"], s.extra["var"].split(",")[0].strip() or "_"
        if meth == "times":
            return self._counted(f"{var} = 0", f"{var} < {recv}", f"{var} = {var} + 1", s.body, pend)
        if meth == "upto":
            hi = s.extra["args"].strip("()")
            return self._counted(f"{var} = {recv}", f"{var} <= {hi}", f"{var} = {var} + 1", s.body, pend)
        if meth == "downto":
            lo = s.extra["args"].strip("()")
            return self._counted(f"{var} = {recv}", f"{var} >= {lo}", f"{var} = {var} - 1", s.body, pend)
        return self._counted(f"{var} = первый элемент {recv}", f"в {recv} остались элементы",
                             f"{var} = следующий элемент {recv}", s.body, pend)

    def loop(self, s: Stmt, pend: Pending) -> Pending:
        l = self.node("loop", "цикл loop"); self.connect(pend, l)
        ctx = self.new_loop()
        mark = len(self.V)
        out = self.seq(s.body, [(l, "")])
        first = mark + 1 if len(self.V) > mark else l
        self.connect(out + ctx["nexts"], first)
        self.loops.pop()
        return ctx["breaks"]


def build_graph(source: str):
    stmts = Parser(prepare(source)).parse()
    b = Builder()
    start = b.node("start", "Начало")
    pend = b.seq(stmts, [(start, "")])
    end = b.node("end", "Конец")
    b.connect(pend + b.returns, end)
    return b.V, b.E


# ---------------------------------------------------------------------------
# 4. Метрика граничных значений
# ---------------------------------------------------------------------------

@dataclass
class SelInfo:
    vertex: int
    transitions: List[int]
    subgraph: List[int]
    lower: Optional[int]
    complexity: int


@dataclass
class BoundaryResult:
    vertices: List[Vertex]
    edges: List[Tuple[int, int, str]]
    selection: Dict[int, SelInfo]
    complexity: Dict[int, int]
    sa: int
    v: int

    @property
    def so(self) -> float:
        return 1 - (self.v - 1) / self.sa if self.sa else 0.0

    def out_edges(self, a: int):
        return [(b, l) for x, b, l in self.edges if x == a]


def compute(V: List[Vertex], E) -> BoundaryResult:
    ids = [v.id for v in V]
    end = ids[-1]
    succ = {i: [] for i in ids}
    for a, b, _ in E:
        succ[a].append(b)
    uniq = {i: sorted(set(s)) for i, s in succ.items()}

    # постдоминаторы
    all_ids = set(ids)
    pd = {i: set(all_ids) for i in ids}
    pd[end] = {end}
    changed = True
    while changed:
        changed = False
        for i in ids:
            if i == end or not uniq[i]:
                continue
            new = {i} | set.intersection(*[pd[s] for s in uniq[i]])
            if new != pd[i]:
                pd[i] = new; changed = True

    def ipdom(v: int) -> Optional[int]:
        cand = pd[v] - {v}
        for x in cand:
            if all(y == x or y in pd[x] for y in cand):
                return x
        return None

    sel: Dict[int, SelInfo] = {}
    comp: Dict[int, int] = {}
    for v in ids:
        if len(succ[v]) >= 2:                       # вершина выбора
            low = ipdom(v)
            seen, st = set(), list(uniq[v])
            while st:
                x = st.pop()
                if x == low or x in seen:
                    continue
                seen.add(x); st += uniq[x]
            s = len(seen) + (1 if low is not None else 0)
            sel[v] = SelInfo(v, uniq[v], sorted(seen), low, s)
            comp[v] = s
        else:                                       # принимающая вершина
            comp[v] = 0 if v == end else 1
    return BoundaryResult(V, list(E), sel, comp, sum(comp.values()), len(ids))


def analyze(source: str) -> BoundaryResult:
    V, E = build_graph(source)
    return compute(V, E)


# ---------------------------------------------------------------------------
# 5. Вывод
# ---------------------------------------------------------------------------

def to_dot(r: BoundaryResult) -> str:
    shape = {"start": "ellipse", "end": "ellipse", "proc": "box", "cond": "diamond",
             "io": "parallelogram", "loop": "hexagon"}
    L = ["digraph G {", "  rankdir=TB; splines=ortho;",
         '  node [fontname="DejaVu Sans", fontsize=11];']
    for v in r.vertices:
        label = v.text if v.kind in ("start", "end") else f"{v.id}. {v.text}"
        label = label.replace('"', '\\"')
        L.append(f'  n{v.id} [shape={shape[v.kind]}, label="{label}"];')
    for a, b, lab in r.edges:
        L.append(f'  n{a} -> n{b}' + (f' [xlabel="{lab}"]' if lab else "") + ";")
    L.append("}")
    return "\n".join(L)


def format_report(r: BoundaryResult) -> str:
    out = [f"Число вершин v = {r.v}",
           f"Вершины выбора: {', '.join(map(str, r.selection)) or '—'}", ""]
    out.append("Свойства подграфов:")
    for v, s in r.selection.items():
        out.append(f"  вершина {v}: переходы {s.transitions}, подграф {s.subgraph}, "
                   f"нижняя граница {s.lower}, сложность {s.complexity}")
    out.append("")
    out.append("Скорректированные сложности: " +
               ", ".join(f"{i}:{c}" for i, c in r.complexity.items()))
    out.append(f"Sa = {r.sa}")
    out.append(f"So = 1 - ({r.v} - 1) / {r.sa} = {r.so:.3f}")
    return "\n".join(out)


def main(argv):
    if len(argv) < 2:
        print(__doc__); return 1
    with open(argv[1], encoding="utf-8") as f:
        r = analyze(f.read())
    print(format_report(r))
    if "--dot" in argv:
        path = argv[argv.index("--dot") + 1]
        with open(path, "w", encoding="utf-8") as f:
            f.write(to_dot(r))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
