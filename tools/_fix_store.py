p = "D:/Longcare/backend/store.py"
s = open(p, encoding="utf-8").read()

# 1) add_resident_message: row_json needs fields arg (no JSON columns here)
old1 = '''        return row_json(self.db.fetch_one("SELECT * FROM resident_messages WHERE id=?", (msg_id,)))'''
new1 = '''        return row_json(self.db.fetch_one("SELECT * FROM resident_messages WHERE id=?", (msg_id,)), ())'''
assert s.count(old1) == 1, "add_resident_message row_json anchor"
s = s.replace(old1, new1, 1)

# 2) upsert INSERT: remove stray extra '?' so placeholders == columns == tuple length (16)
old2 = 'id,subject_id,memory_type,title,content_text,attributes_json,confidence,status,requires_confirmation,source_driver,source_run_id,confirmed_at,invalidated_at,created_at,updated_at,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"'
new2 = 'id,subject_id,memory_type,title,content_text,attributes_json,confidence,status,requires_confirmation,source_driver,source_run_id,confirmed_at,invalidated_at,created_at,updated_at,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"'
assert s.count(old2) == 1, "upsert INSERT anchor"
s = s.replace(old2, new2, 1)

# 3a) resident_messages: split ORDER/LIMIT out of AND-JOIN
old3 = '''        clauses, params = ["subject_id=?"], [self.settings.subject_id]
        if conversation_id:
            clauses.append("conversation_id=?"); params.append(conversation_id)
        clauses.append("ORDER BY created_at ASC LIMIT ?"); params.append(limit)
        return self.db.fetch_all(f"SELECT * FROM resident_messages WHERE {' AND '.join(clauses)}", tuple(params))'''
new3 = '''        where, params = ["subject_id=?"], [self.settings.subject_id]
        if conversation_id:
            where.append("conversation_id=?"); params.append(conversation_id)
        sql = "SELECT * FROM resident_messages WHERE " + " AND ".join(where) + f" ORDER BY created_at ASC LIMIT {int(limit)}"
        return self.db.fetch_all(sql, tuple(params))'''
assert s.count(old3) == 1, "resident_messages anchor"
s = s.replace(old3, new3, 1)

# 3b) resident_memory: same fix
old4 = '''        clauses, params = ["subject_id=?"], [self.settings.subject_id]
        if status:
            clauses.append("status=?"); params.append(status)
        if source_driver:
            clauses.append("source_driver=?"); params.append(source_driver)
        clauses.append("ORDER BY updated_at DESC LIMIT ?"); params.append(limit)
        return [row_json(r, ("attributes_json",)) for r in self.db.fetch_all(
            f"SELECT * FROM resident_memories WHERE {' AND '.join(clauses)}", tuple(params))]'''
new4 = '''        where, params = ["subject_id=?"], [self.settings.subject_id]
        if status:
            where.append("status=?"); params.append(status)
        if source_driver:
            where.append("source_driver=?"); params.append(source_driver)
        sql = "SELECT * FROM resident_memories WHERE " + " AND ".join(where) + f" ORDER BY updated_at DESC LIMIT {int(limit)}"
        return [row_json(r, ("attributes_json",)) for r in self.db.fetch_all(sql, tuple(params))]'''
assert s.count(old4) == 1, "resident_memory anchor"
s = s.replace(old4, new4, 1)

# 3c) understanding_insights: same fix
old5 = '''        clauses, params = ["subject_id=?"], [self.settings.subject_id]
        if status:
            clauses.append("status=?"); params.append(status)
        clauses.append("ORDER BY created_at DESC LIMIT ?"); params.append(limit)
        return [row_json(r, ("preference_hypotheses_json", "state_hypotheses_json", "initiation_reasons_json", "policy_json"))
                for r in self.db.fetch_all(f"SELECT * FROM resident_understanding_insights WHERE {' AND '.join(clauses)}", tuple(params))]'''
new5 = '''        where, params = ["subject_id=?"], [self.settings.subject_id]
        if status:
            where.append("status=?"); params.append(status)
        sql = "SELECT * FROM resident_understanding_insights WHERE " + " AND ".join(where) + f" ORDER BY created_at DESC LIMIT {int(limit)}"
        return [row_json(r, ("preference_hypotheses_json", "state_hypotheses_json", "initiation_reasons_json", "policy_json"))
                for r in self.db.fetch_all(sql, tuple(params))]'''
assert s.count(old5) == 1, "understanding_insights anchor"
s = s.replace(old5, new5, 1)

# 3d) resident_runs: same fix (had ORDER in clauses too)
old6 = '''        clauses, params = ["subject_id=?"], [self.settings.subject_id]
        if driver:
            clauses.append("driver=?"); params.append(driver)
        clauses.append("ORDER BY created_at DESC LIMIT ?"); params.append(limit)
        return [row_json(r, ("input_json", "output_json")) for r in self.db.fetch_all(
            f"SELECT * FROM resident_agent_runs WHERE {' AND '.join(clauses)}", tuple(params))]'''
new6 = '''        where, params = ["subject_id=?"], [self.settings.subject_id]
        if driver:
            where.append("driver=?"); params.append(driver)
        sql = "SELECT * FROM resident_agent_runs WHERE " + " AND ".join(where) + f" ORDER BY created_at DESC LIMIT {int(limit)}"
        return [row_json(r, ("input_json", "output_json")) for r in self.db.fetch_all(sql, tuple(params))]'''
assert s.count(old6) == 1, "resident_runs anchor"
s = s.replace(old6, new6, 1)

open(p, "w", encoding="utf-8").write(s)
print("store.py bug fixes applied")
