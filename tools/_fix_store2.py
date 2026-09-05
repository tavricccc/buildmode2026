p = "D:/Longcare/backend/store.py"
s = open(p, encoding="utf-8").read()

# record_resident_run: trigger_id not a real column; dedup uses conversation_id instead
old1 = '''        dedup_key = f"{driver}:{trigger_type}:{trigger_id}:{self.settings.config_version}"
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM resident_agent_runs WHERE dedup_key=?", (dedup_key,)).fetchone():
                return self.resident_run_by_id(conn.execute("SELECT id FROM resident_agent_runs WHERE dedup_key=? ORDER BY created_at DESC LIMIT 1", (dedup_key,)).fetchone()["id"])
            conn.execute(
                "INSERT INTO resident_agent_runs(id,subject_id,conversation_id,driver,trigger_type,trigger_id,status,action,input_json,output_json,provider,model,latency_ms,error_code,created_at,completed_at,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, self.settings.subject_id, conversation_id, driver, trigger_type, trigger_id, status, action,
                 self.db.dumps(input_json), self.db.dumps(output_json) if output_json is not None else None,
                 provider, model, latency_ms, error_code, now, now, dedup_key))'''
new1 = '''        dedup_key = f"{driver}:{trigger_type}:{conversation_id or 'default'}:{self.settings.config_version}"
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM resident_agent_runs WHERE dedup_key=?", (dedup_key,)).fetchone():
                return self.resident_run_by_id(conn.execute("SELECT id FROM resident_agent_runs WHERE dedup_key=? ORDER BY created_at DESC LIMIT 1", (dedup_key,)).fetchone()["id"])
            conn.execute(
                "INSERT INTO resident_agent_runs(id,subject_id,conversation_id,driver,trigger_type,status,action,input_json,output_json,provider,model,latency_ms,error_code,created_at,completed_at,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, self.settings.subject_id, conversation_id, driver, trigger_type, status, action,
                 self.db.dumps(input_json), self.db.dumps(output_json) if output_json is not None else None,
                 provider, model, latency_ms, error_code, now, now, dedup_key))'''
assert s.count(old1) == 1, "record_resident_run anchor"
s = s.replace(old1, new1, 1)

# upsert INSERT: exactly 16 placeholders for 16 columns
old2 = 'status,requires_confirmation,source_driver,source_run_id,confirmed_at,invalidated_at,created_at,updated_at,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"'
new2 = 'status,requires_confirmation,source_driver,source_run_id,confirmed_at,invalidated_at,created_at,updated_at,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"'
assert s.count(old2) == 1, "upsert INSERT anchor"
s = s.replace(old2, new2, 1)

open(p, "w", encoding="utf-8").write(s)
print("store.py record_resident_run + upsert fixed")
