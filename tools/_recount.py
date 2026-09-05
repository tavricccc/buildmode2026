import ast, re
src = open("D:/Longcare/backend/store.py", encoding="utf-8").read()
i = src.index('INSERT INTO resident_agent_runs')
tail = src[i:]
# columns in first parenthetical after INTO
cstart = tail.index('(')
cend = tail.index(')', cstart)
cols = len(tail[cstart+1:cend].split(','))
# VALUES placeholders
vstart = tail.index('VALUES') + 6
vp = tail.index('(', vstart)
vend = tail.index(')', vp)
qmarks = tail[vp+1:vend].count('?')
print("cols:", cols, "placeholders:", qmarks)
