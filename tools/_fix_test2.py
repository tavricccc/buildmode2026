p = "D:/Longcare/backend/tests/test_resident.py"
s = open(p, encoding="utf-8").read()
old = '''def _make_agent(store, **fake_kwargs):
    settings = store.settings
    return ResidentInteractionAgent(settings, store,
                                    vision=_FakeAsr(**fake_kwargs), asr=_FakeAsr(transcript=fake_kwargs.get("transcript", "")),
                                    tts=_FakeTts())'''
new = '''def _make_agent(store, reply_raw=None, insight_raw=None, transcript=""):
    settings = store.settings
    return ResidentInteractionAgent(settings, store,
                                    vision=_FakeVision(reply_raw=reply_raw, insight_raw=insight_raw),
                                    asr=_FakeAsr(transcript=transcript),
                                    tts=_FakeTts())'''
assert s.count(old) == 1, "_make_agent anchor"
s = s.replace(old, new, 1)
open(p, "w", encoding="utf-8").write(s)
print("test _make_agent fixed")
