# Анализируемая программа на языке Ruby для расчёта метрики Джилба.
# Содержит все операторы цикла (while, until, for, loop),
# операторы ветвления (if/elsif/else, unless) и оператор
# множественного выбора (case/when).
 
n = 5
sum = 0
i = 1
 
# Цикл с предусловием while: сумма чисел от 1 до n
while i <= n
  sum += i
  i += 1
end
 
# Цикл until: обратный отсчёт
countdown = n
until countdown == 0
  countdown -= 1
end
 
# Цикл for с ветвлением if/elsif/else: подсчёт чётных и нечётных
evens = 0
odds = 0
for k in 1..n
  if k % 2 == 0
    evens += 1
  elsif k == n
    odds += 2
  else
    odds += 1
  end
end
 
# Цикл loop с условием выхода
limit = sum / 2
value = 0
loop do
  value += 1
  break if value > limit
end
 
# Оператор-модификатор unless
puts "Сумма ненулевая" unless sum == 0
 
# Оператор множественного выбора case
category = ""
case
when sum < 10
  category = "малое"
when sum < 20
  category = "среднее"
when sum < 40
  category = "большое"
else
  category = "очень большое"
end
 
puts "sum=#{sum}, evens=#{evens}, odds=#{odds}, value=#{value}, category=#{category}"
