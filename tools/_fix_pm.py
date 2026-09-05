p = "D:/Longcare/backend/store.py"
s = open(p, encoding="utf-8").read()
old = '(id,subject_id,conversation_id,driver,trigger_type,status,action,input_json,output_json,provider,model,latency_ms,error_code,created_at,completed_at,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"'
new = '(id,subject_id,conversation_id,driver,trigger_type,status,action,input_json,output_json,provider,model,latency_ms,error_code,created_at,completed_at,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"'
assert s.count(old) == 1, "pm anchor"
s = s.replace(old, new, 1)
open(p, "w", encoding="utf-8").write(s)
print("placeholder count fixed to 16")
