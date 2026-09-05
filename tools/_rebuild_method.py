p = "D:/Longcare/backend/store.py"
raw = open(p, encoding="utf-8").read()
CR = "\r\n"
lines_in = raw.split(CR)
# find start of method def and next method def
start = None
end = None
for idx, ln in enumerate(lines_in):
    if ln.strip().startswith("def record_resident_run("):
        start = idx
    elif start is not None and ln.startswith("    def resident_run_by_id("):
        end = idx
        break
assert start is not None and end is not None, (start, end)

body_lines = [
    "    def record_resident_run(self, *, driver: str, trigger_type: str, trigger_id: str,",
    "                            conversation_id: str | None, status: str, action: str,",
    "                            input_json: dict[str, Any], output_json: dict[str, Any] | None = None,",
    "                            provider: str = \"\", model: str = \"\", latency_ms: int | None = None,",
    "                            error_code: str | None = None) -> dict:",
    '        run_id = make_id("resrun")',
    "        now = now_iso()",
    "        dedup_key = f\"{driver}:{trigger_type}:{conversation_id or 'default'}:{self.settings.config_version}\"",
    "        with self.db.transaction() as conn:",
    '            if conn.execute("SELECT 1 FROM resident_agent_runs WHERE dedup_key=?", (dedup_key,)).fetchone():',
    '                return self.resident_run_by_id(conn.execute("SELECT id FROM resident_agent_runs WHERE dedup_key=? ORDER BY created_at DESC LIMIT 1", (dedup_key,)).fetchone()["id"])',
    "            conn.execute(",
    '                "INSERT INTO resident_agent_runs(id,subject_id,conversation_id,driver,trigger_type,status,action,input_json,output_json,provider,model,latency_ms,error_code,created_at,completed_at,dedup_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",',
    "                (run_id, self.settings.subject_id, conversation_id, driver, trigger_type, status, action,",
    "                 self.db.dumps(input_json), self.db.dumps(output_json) if output_json is not None else None,",
    "                 provider, model, latency_ms, error_code, now, now, dedup_key))",
    '        return row_json(self.db.fetch_one("SELECT * FROM resident_agent_runs WHERE id=?", (run_id,)),',
    '                        ("input_json", "output_json"))',
    "",
]
new_block = CR.join(body_lines)
out = CR.join(lines_in[:start]) + new_block + CR.join(lines_in[end:])
open(p, "w", encoding="utf-8", newline="").write(out)
print("record_resident_run rebuilt cleanly")
