src = open("D:/Longcare/backend/store.py", encoding="utf-8").read()
i = src.index('INSERT INTO resident_memories')
tail = src[i:]
open_paren = tail.index('(')
close = tail.index(')', open_paren)
inside = tail[open_paren+1:close]
print("columns:", len(inside.split(',')))
qmarks = inside.count('?')
print("question marks:", qmarks)
# value tuple length
val_start = tail.index('(', tail.index('VALUES'))
