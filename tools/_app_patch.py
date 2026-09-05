path = "D:/Longcare/backend/app.py"
with open(path, encoding="utf-8") as f:
    src = f.read()

def must(old, label):
    assert src.count(old) >= 1, f"[{label}] anchor not found"

# 1) imports: base64 + resident orchestrator
must("\nimport asyncio\n", "asyncio-import")
src = src.replace("\nimport asyncio\n", "\nimport asyncio\nimport base64\n", 1)
must("from .adapters import FrigateAdapter, MiniMaxAdapter, TelegramAdapter, VllmVisionAdapter\n", "adapters-import")
src = src.replace(
    "from .adapters import FrigateAdapter, MiniMaxAdapter, TelegramAdapter, VllmVisionAdapter\n",
    "from .adapters import FrigateAdapter, MiniMaxAdapter, TelegramAdapter, VllmVisionAdapter\n"
    "from .resident import ResidentInteractionAgent\n", 1)

# 2) request schemas (single long line): add resident models before WindowRequest
must("from .schemas import AudioTranscriptRequest, CaptureStatusRequest, FrigateEventRequest,", "schemas-import")
src = src.replace(
    "from .schemas import AudioTranscriptRequest, CaptureStatusRequest, FrigateEventRequest,",
    "from .schemas import AudioTranscriptRequest, CaptureStatusRequest, FrigateEventRequest,\n"
    "    ResidentMemoryUpdateRequest, ResidentMessageRequest,", 1)

# 3) orchestrator singleton next to vllm
must("vllm = VllmVisionAdapter(settings)\n", "vllm-singleton")
src = src.replace(
    "vllm = VllmVisionAdapter(settings)\n",
    "vllm = VllmVisionAdapter(settings)\n"
    "resident_agent = ResidentInteractionAgent(settings, store, vision=vllm)\n", 1)

# 4) background loop definition right before media_bridge
must("media_bridge = VirtualCameraBridge(", "media-bridge")
loop_block = '''async def resident_background_loop() -> None:
    """Silent understanding/motivation driver; only proposes, never speaks."""
    while True:
        await asyncio.sleep(settings.resident_understanding_interval_seconds)
        try:
            await resident_agent.background_run(conversation_id="default")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            store.log("error", "resident_understanding", "Resident understanding run failed closed",
                      context={"error": type(exc).__name__})


'''
src = src.replace("media_bridge = VirtualCameraBridge(", loop_block + "media_bridge = VirtualCameraBridge(", 1)

# 5) lifespan: global decl
must("    global periodic_summary_task\n", "lifespan-global")
src = src.replace("    global periodic_summary_task\n",
                  "    global periodic_summary_task\n    global resident_understanding_task\n", 1)

# 6) lifespan: start block
must('        periodic_summary_task = asyncio.create_task(periodic_summary_loop(), name="main-agent-periodic-summary")\n', "start-block")
src = src.replace(
    '        periodic_summary_task = asyncio.create_task(periodic_summary_loop(), name="main-agent-periodic-summary")\n',
    '        periodic_summary_task = asyncio.create_task(periodic_summary_loop(), name="main-agent-periodic-summary")\n'
    "        if settings.resident_understanding_interval_seconds > 0:\n"
    '            resident_understanding_task = asyncio.create_task(resident_background_loop(), name="resident-understanding-loop")\n', 1)

# 7) lifespan: cancel block
must("        periodic_summary_task = None\n", "cancel-block")
src = src.replace(
    "        periodic_summary_task = None\n",
    "        periodic_summary_task = None\n"
    "        if resident_understanding_task:\n"
    "            resident_understanding_task.cancel()\n"
    "            await asyncio.gather(resident_understanding_task, return_exceptions=True)\n"
    "            resident_understanding_task = None\n", 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(src)
print("app.py core wiring patched OK")
