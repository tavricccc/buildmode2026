p = "D:/Longcare/backend/store.py"
s = open(p, encoding="utf-8").read()
bad = 'status,action,input_json,output_json,provider,model,latency_ms,error_code,created_at,completed_at,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"'
good = 'status,action,input_json,output_json,provider,model,latency_ms,error_code,created_at,completed_at,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"'
assert s.count(bad) == 1, "bad placeholders anchor"
s = s.replace(bad, good, 1)
open(p, "w", encoding="utf-8").write(s)
print("removed one stray ? -> now 16")
