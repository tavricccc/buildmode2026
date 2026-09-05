import re
src = open("D:/Longcare/backend/store.py", encoding="utf-8").read()
i = src.index("INSERT INTO resident_agent_runs")
t = src[i:]
# columns paren after INSERT INTO name
a = t.index("(")
b = t.index(")", a)
cols = t[a+1:b].split(",")
# VALUES (...)
vpos = t.index("VALUES") + 6
c = t.index("(", vpos)
d = t.index(")", c)
ph = t[c+1:d]
print("columns:", len(cols))
print("placeholders chars (? count):", ph.count("?"))
# now find the tuple right after VALUES(...) 
tuple_start = t.index("(run_id", c)
tuple_end = t.index("\n", tuple_start)
tup = t[tuple_start:tuple_end]
vals = [x.strip() for x in re.split(r",(?=\S)", tup)[1:] if x.strip()]
print("tuple values:", len(vals))
