src = open("D:/Longcare/backend/store.py", encoding="utf-8").read()
i = src.index('INSERT INTO resident_memories')
print(repr(src[i:i+950]))
