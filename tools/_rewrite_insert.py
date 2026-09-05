p = "D:/Longcare/backend/store.py"
s = open(p, encoding="utf-8").read()

cols = ["id","subject_id","conversation_id","driver","trigger_type","status","action",
        "input_json","output_json","provider","model","latency_ms","error_code",
        "created_at","completed_at","dedup_key"]
assert len(cols) == 16, f"expected 16 cols, got {len(cols)}"
placeholders = "(" + ",".join(["?"]*len(cols)) + ")"
sql_cols = ",".join(cols)

old_sql_frag = "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
new_sql_frag = f"VALUES{placeholders}"
assert old_sql_frag in s, "old VALUES fragment not found"
s = s.replace(old_sql_frag, new_sql_frag, 1)

# also fix the resident_memories insert placeholders to match its column count if mismatched
mcols = ["id","subject_id","memory_type","title","content_text","attributes_json",
         "confidence","status","requires_confirmation","source_driver","source_run_id",
         "confirmed_at","invalidated_at","created_at","updated_at","dedup_key"]
assert len(mcols) == 16, f"memories expected 16 cols, got {len(mcols)}"
mfrag = "(" + ",".join(["?"]*len(mcols)) + ")"
old_mfrag = "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
s = s.replace(old_mfrag, mfrag, 1)

open(p, "w", encoding="utf-8").write(s)
print(f"rewrote placeholders: runs={placeholders} memories={mfrag}")
