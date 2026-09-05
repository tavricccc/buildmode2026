p = "D:/Longcare/backend/tests/test_resident.py"
s = open(p, encoding="utf-8").read()

# 1) _make_agent: vision should use a fake that exposes both analyze methods -> base _FakeAdapter
old1 = '''def _make_agent(store, reply_raw=None, insight_raw=None, transcript=""):
    settings = store.settings
    return ResidentInteractionAgent(settings, store,
                                    vision=_FakeVision(reply_raw=reply_raw, insight_raw=insight_raw),
                                    asr=_FakeAsr(transcript=transcript),
                                    tts=_FakeTts())'''
new1 = '''def _make_agent(store, reply_raw=None, insight_raw=None, transcript=""):
    settings = store.settings
    vision = _FakeAdapter(reply_raw=reply_raw or {}, insight_raw=insight_raw or {})
    return ResidentInteractionAgent(settings, store,
                                    vision=vision, asr=_FakeAsr(transcript=transcript),
                                    tts=_FakeTts())'''
assert s.count(old1) == 1, "_make_agent v2 anchor"
s = s.replace(old1, new1, 1)

# 2) fix round-trip assertion: check both ids present (not  truthiness)
old2 = '''        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
        self.assertEqual(user["id"] and assistant["id"], True)'''
new2 = '''        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
        self.assertTrue(user["id"])
        self.assertTrue(assistant["id"])'''
assert s.count(old2) == 1, "roundtrip assert anchor"
s = s.replace(old2, new2, 1)

# 3) understanding insight direct-store: store echoes given status; pass explicit proceed
old3 = '''        insight = self.store.record_understanding_insight(run_id="r1", observed_pattern="午後未起身", user_perspective="或許需要提醒",
                                                          should_initiate=True, suggested_message="要提醒你起來活動一下嗎？", confidence=0.9)
        self.assertEqual(insight["status"], "proceed")'''
new3 = '''        stored = self.store.record_understanding_insight(run_id="r1", observed_pattern="午後未起身", user_perspective="或許需要提醒",
                                                          should_initiate=True, suggested_message="要提醒你起來活動一下嗎？", confidence=0.9,
                                                          status="proceed")
        self.assertEqual(stored["status"], "proceed")'''
assert s.count(old3) == 1, "insight store anchor"
s = s.replace(old3, new3, 1)

open(p, "w", encoding="utf-8").write(s)
print("test fixes applied")
