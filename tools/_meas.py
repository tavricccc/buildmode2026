import ast, re
src = open("D:/Longcare/backend/store.py", encoding="utf-8").read()
i = src.index('INSERT INTO resident_agent_runs')
tail = src[i:]
cstart = tail.index('('); cend = tail.index(')', cstart)
cols = len(tail[cstart+1:cend].split(','))
vstart = tail.index('VALUES')+6; vp = tail.index('(', vstart); vend = tail.index(')', vp)
qmarks = tail[vp+1:vend].count('?')
# find tuple after VALUES(...)
tstart = tail.index('(run_id', vp)
tclose = tail.index('\n', tstart)
tup = tail[tstart:tclose]
# naive comma-split ignoring ternary: just count top-level by stripping 'if...else'
body = re.sub(r' if .*? else .*?', '', tup)
vals = [x for x in body.split(',') if x.strip()]
print("cols:", cols, "placeholders:", qmarks, "tuple_vals:", len(vals))
