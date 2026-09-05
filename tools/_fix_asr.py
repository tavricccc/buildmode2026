p = "D:/Longcare/backend/tests/test_resident.py"
s = open(p, encoding="utf-8").read()
old = '''        return AdapterResult("unavailable", {"asr": {"speech_detected": False, "transcript": "",
                             "language": "unknown", "confidence": 0.0,
                             "uncertainty_reasons": ["GMI MiniMax M3 did not expose the supplied audio to the model"]}, "GMI_M3_AUDIO_NOT_ACCEPTED")'''
new = '''        unavailable_asr = {"speech_detected": False, "transcript": "", "language": "unknown",
                           "confidence": 0.0,
                           "uncertainty_reasons": ["GMI MiniMax M3 did not expose the supplied audio to the model"]}
        return AdapterResult("unavailable", {"asr": unavailable_asr}, "GMI_M3_AUDIO_NOT_ACCEPTED")'''
assert old in s, "ASR block not found"
s = s.replace(old, new, 1)
open(p, "w", encoding="utf-8").write(s)
print("ASR fix applied")
