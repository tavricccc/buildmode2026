p = "D:/Longcare/backend/tests/test_resident.py"
s = open(p, encoding="utf-8").read()
old = '        tools = self.store.record_tool_call.__self__.tool_calls(limit=10)\n'
new = '        tools = self.store.tool_calls(limit=50)\n'
assert old in s, "target line not found"
s = s.replace(old, new, 1)
open(p, "w", encoding="utf-8").write(s)
print("test fixed")
