import re
src = open("D:/Longcare/backend/store.py", encoding="utf-8").read()
# find the INSERT for resident_memories m
i = src.index('INSERT INTO resident_memories')
snippet = src[i:i+900]
qmarks = len(re.findall(r"\?", snippet))
print("placeholder count:", qmarks)
