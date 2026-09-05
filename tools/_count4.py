src = open("D:/Longcare/backend/store.py", encoding="utf-8").read()
i = src.index('INSERT INTO resident_memories')
tail = src[i:]
val_open = tail.index('VALUES') + 6
vparen = tail.index('(', val_open)
close = tail.index(')', vparen)
inside = tail[vparen+1:close]
print("VALUES inside:", repr(inside))
cols_start = tail.index('(')
cend = tail.index(')', cols_start)
print("COLUMNS:", len(tail[cols_start+1:cend].split(',')))
