path = "D:/Longcare/backend/app.py"
with open(path, encoding="utf-8") as f:
    src = f.read()

bad = ("from .schemas import AudioTranscriptRequest, CaptureStatusRequest, FrigateEventRequest,\n"
       "    ResidentMemoryUpdateRequest, ResidentMessageRequest, HealthScenarioRequest, MainAgentJudgment, ModelDownloadRequest, ReplayLoadRequest, SetupSettingsPatch, SourceActivateRequest, VadActivityRequest, WindowRequest, VisionObservation\n")

good = ("from .schemas import (\n"
        "    AudioTranscriptRequest, CaptureStatusRequest, FrigateEventRequest, HealthScenarioRequest,\n"
        "    MainAgentJudgment, ModelDownloadRequest, ReplayLoadRequest, SetupSettingsPatch,\n"
        "    SourceActivateRequest, VadActivityRequest, WindowRequest, VisionObservation,\n"
        "    ResidentMemoryUpdateRequest, ResidentMessageRequest,\n"
        ")\n")

assert bad in src, "broken import block not found"
src = src.replace(bad, good, 1)
with open(path, "w", encoding="utf-8") as f:
    f.write(src)
print("schemas import fixed")
