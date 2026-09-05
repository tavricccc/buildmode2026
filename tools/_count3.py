import ast
src = open("D:/Longcare/backend/store.py", encoding="utf-8").read()
i = src.index('INSERT INTO resident_memories')
tail = src[i:]
val_open = tail.index('VALUES') + 6
vparen = tail.index('(', val_open)
close = tail.index(')', vparen)
placeholders = tail[vparen+1:close].count('?')
print("placeholders in VALUES:", placeholders)
# value tuple
tstart = tail.index('(mem_id', vparen)
tclose = tail.index('\n', tstart)
tup_str = tail[tstart:tclose]
elts = ast.parse(tup_str, mode='eval').body.elts
print("tuple elements:", len(elts))
