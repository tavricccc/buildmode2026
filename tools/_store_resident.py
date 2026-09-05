path = "D:/Longcare/backend/store.py"
with open(path, encoding="utf-8") as f:
    src = f.read()

marker = "    def _frigate_decision(self, detections: list[dict[str, Any]], explicit: bool | None = None) -> tuple[bool, str]:"
assert marker in src, "marker not found"

block = '''    # --- Resident Interaction Agent persistence (two driver layers) ---
    def record_resident_run(self, *, driver: str, trigger_type: str, trigger_id: str,
                            conversation_id: str | None, status: str, action: str,
                            input_json: dict[str, Any], output_json: dict[str, Any] | None = None,
                            provider: str = "", model: str = "", latency_ms: int | None = None,
                            error_code: str | None = None) -> dict:
        run_id = make_id("resrun")
        now = now_iso()
        dedup_key = f"{driver}:{trigger_type}:{trigger_id}:{self.settings.config_version}"
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM resident_agent_runs WHERE dedup_key=?", (dedup_key,)).fetchone():
                return self.resident_run_by_id(conn.execute("SELECT id FROM resident_agent_runs WHERE dedup_key=? ORDER BY created_at DESC LIMIT 1", (dedup_key,)).fetchone()["id"])
            conn.execute(
                "INSERT INTO resident_agent_runs(id,subject_id,conversation_id,driver,trigger_type,trigger_id,status,action,input_json,output_json,provider,model,latency_ms,error_code,created_at,completed_at,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, self.settings.subject_id, conversation_id, driver, trigger_type, trigger_id, status, action,
                 self.db.dumps(input_json), self.db.dumps(output_json) if output_json is not None else None,
                 provider, model, latency_ms, error_code, now, now, dedup_key))
        return row_json(self.db.fetch_one("SELECT * FROM resident_agent_runs WHERE id=?", (run_id,)),
                        ("input_json", "output_json"))

    def resident_run_by_id(self, run_id: str) -> dict | None:
        row = self.db.fetch_one("SELECT * FROM resident_agent_runs WHERE id=?", (run_id,))
        return row_json(row, ("input_json", "output_json")) if row else None

    def resident_runs(self, *, driver: str | None = None, limit: int = 100) -> list[dict]:
        clauses, params = ["subject_id=?"], [self.settings.subject_id]
        if driver:
            clauses.append("driver=?"); params.append(driver)
        clauses.append("ORDER BY created_at DESC LIMIT ?"); params.append(limit)
        return [row_json(r, ("input_json", "output_json")) for r in self.db.fetch_all(
            f"SELECT * FROM resident_agent_runs WHERE {' AND '.join(clauses)}", tuple(params))]

    def add_resident_message(self, *, conversation_id: str, role: str, text: str,
                             intent: str | None = None, run_id: str | None = None,
                             asr_status: str | None = None, tts_artifact_id: str | None = None) -> dict:
        msg_id = make_id("resmsg")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO resident_messages(id,subject_id,conversation_id,role,text,intent,run_id,asr_status,tts_artifact_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (msg_id, self.settings.subject_id, conversation_id, role, text, intent, run_id, asr_status, tts_artifact_id, now_iso()))
        return row_json(self.db.fetch_one("SELECT * FROM resident_messages WHERE id=?", (msg_id,)))

    def resident_messages(self, *, conversation_id: str | None = None, limit: int = 200) -> list[dict]:
        clauses, params = ["subject_id=?"], [self.settings.subject_id]
        if conversation_id:
            clauses.append("conversation_id=?"); params.append(conversation_id)
        clauses.append("ORDER BY created_at ASC LIMIT ?"); params.append(limit)
        return self.db.fetch_all(f"SELECT * FROM resident_messages WHERE {' AND '.join(clauses)}", tuple(params))

    def upsert_resident_memory(self, *, memory_type: str, title: str, content: str, confidence: float,
                               requires_confirmation: bool = True, source_driver: str = "understanding",
                               source_run_id: str | None = None) -> dict:
        dedup_key = f"{source_driver}:{title}:{content[:200]}"
        existing = self.db.fetch_one("SELECT * FROM resident_memories WHERE subject_id=? AND dedup_key=?", (self.settings.subject_id, dedup_key))
        now = now_iso()
        status = "pending" if requires_confirmation else "confirmed"
        if existing:
            mem_id = existing["id"]
            with self.db.transaction() as conn:
                conn.execute("UPDATE resident_memories SET confidence=?, memory_type=?, content_text=?, status=?, requires_confirmation=?, updated_at=? WHERE id=?",
                             (confidence, memory_type, content, status, 0 if not requires_confirmation else 1, now, mem_id))
        else:
            mem_id = make_id("resmem")
            with self.db.transaction() as conn:
                conn.execute("INSERT INTO resident_memories(id,subject_id,memory_type,title,content_text,attributes_json,confidence,status,requires_confirmation,source_driver,source_run_id,confirmed_at,invalidated_at,created_at,updated_at,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (mem_id, self.settings.subject_id, memory_type, title, content, self.db.dumps({}), confidence, status, 0 if not requires_confirmation else 1, source_driver, source_run_id, None, None, now, now, dedup_key))
        return self.resident_memory_by_id(mem_id)

    def resolve_resident_memory(self, memory_id: str, action: str) -> dict | None:
        mem = self.db.fetch_one("SELECT * FROM resident_memories WHERE id=? AND subject_id=?", (memory_id, self.settings.subject_id))
        if not mem:
            return None
        now = now_iso()
        with self.db.transaction() as conn:
            if action == "confirm":
                conn.execute("UPDATE resident_memories SET status='confirmed', requires_confirmation=0, confirmed_at=?, updated_at=? WHERE id=?", (now, now, memory_id))
            elif action == "invalidate":
                conn.execute("UPDATE resident_memories SET status='invalidated', invalidated_at=?, updated_at=? WHERE id=?", (now, now, memory_id))
        return self.resident_memory_by_id(memory_id)

    def resident_memory(self, *, status: str | None = None, source_driver: str | None = None, limit: int = 100) -> list[dict]:
        clauses, params = ["subject_id=?"], [self.settings.subject_id]
        if status:
            clauses.append("status=?"); params.append(status)
        if source_driver:
            clauses.append("source_driver=?"); params.append(source_driver)
        clauses.append("ORDER BY updated_at DESC LIMIT ?"); params.append(limit)
        return [row_json(r, ("attributes_json",)) for r in self.db.fetch_all(
            f"SELECT * FROM resident_memories WHERE {' AND '.join(clauses)}", tuple(params))]

    def resident_memory_by_id(self, memory_id: str) -> dict | None:
        row = self.db.fetch_one("SELECT * FROM resident_memories WHERE id=?", (memory_id,))
        return row_json(row, ("attributes_json",)) if row else None

    def record_understanding_insight(self, *, run_id: str, observed_pattern: str, user_perspective: str,
                                     preference_hypotheses: list[str] | None = None, state_hypotheses: list[str] | None = None,
                                     should_initiate: bool = False, suggested_message: str = "", initiation_reasons: list[str] | None = None,
                                     confidence: float, policy_json: dict[str, Any] | None = None, status: str = "proposed") -> dict:
        ins_id = make_id("resins")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO resident_understanding_insights(id,subject_id,run_id,observed_pattern,user_perspective,preference_hypotheses_json,state_hypotheses_json,should_initiate,suggested_message,initiation_reasons_json,confidence,policy_json,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (ins_id, self.settings.subject_id, run_id, observed_pattern, user_perspective,
                          self.db.dumps(preference_hypotheses or []), self.db.dumps(state_hypotheses or []),
                          1 if should_initiate else 0, suggested_message, self.db.dumps(initiation_reasons or []), confidence,
                          self.db.dumps(policy_json or {}), status, now_iso()))
        return row_json(self.db.fetch_one("SELECT * FROM resident_understanding_insights WHERE id=?", (ins_id,)),
                        ("preference_hypotheses_json", "state_hypotheses_json", "initiation_reasons_json", "policy_json"))

    def understanding_insights(self, *, status: str | None = None, limit: int = 100) -> list[dict]:
        clauses, params = ["subject_id=?"], [self.settings.subject_id]
        if status:
            clauses.append("status=?"); params.append(status)
        clauses.append("ORDER BY created_at DESC LIMIT ?"); params.append(limit)
        return [row_json(r, ("preference_hypotheses_json", "state_hypotheses_json", "initiation_reasons_json", "policy_json"))
                for r in self.db.fetch_all(f"SELECT * FROM resident_understanding_insights WHERE {' AND '.join(clauses)}", tuple(params))]

'''

src = src.replace(marker, block + marker, 1)
with open(path, "w", encoding="utf-8") as f:
    f.write(src)
print("store.py resident methods inserted OK")
