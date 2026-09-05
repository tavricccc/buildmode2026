p = "D:/Longcare/backend/store.py"
s = open(p, encoding="utf-8").read()
cols = ["id","subject_id","conversation_id","driver","trigger_type","status","action",
        "input_json","output_json","provider","model","latency_ms","error_code",
        "created_at","completed_at","dedup_key"]
n = len(cols)
sql = '"INSERT INTO resident_agent_runs(' + ",".join(cols)       + ') VALUES' + "(" + ",".join(["?"]*n) + ")"       + ", (run_id, self.settings.subject_id, conversation_id, driver, trigger_type, status, action,\n"       + "                 self.db.dumps(input_json), self.db.dumps(output_json) if output_json is not None else None,\n"       + "                 provider, model, latency_ms, error_code, now, now, dedup_key))"
# match the whole conn.execute( ... ) block for resident_agent_runs INSERT only
start = s.index('conn.execute(\n                "INSERT INTO resident_agent_runs')
paren = s.index("(", start)
end = s.index(")", paren)  # first close of conn.execute(
old_block = s[start:end+1]
s2 = s[:start] + sql + s[end+1:]
# verify no stray placeholders remain mismatched
import re
i = s2.index("INSERT INTO resident_agent_runs")
t = s2[i:]; a=t.index("("); b=t.index(")",a); cols_c=len(t[a+1:b].split(","))
c=t.index("VALUES")+6; dd=t.index("(",c); ee=t.index(")",c)
print("cols", cols_c, "placeholders", t[dd+1:ee].count("?"))
open(p,"w",encoding="utf-8").write(s2)
