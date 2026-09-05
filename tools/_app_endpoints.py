path = "D:/Longcare/backend/app.py"
with open(path, encoding="utf-8") as f:
    src = f.read()

anchor = '@app.get("/api/logs")'
assert anchor in src, "logs endpoint anchor not found"

block = '''@app.get("/api/resident/status")
async def resident_status():
    return {
        "conversation_id": "default",
        "minimax_configured": settings.minimax_configured,
        "tts_configured": resident_agent.tts_configured,
        "proactive_enabled": settings.resident_proactive_speech_enabled,
        "understanding_interval_seconds": settings.resident_understanding_interval_seconds,
        "stop_active": resident_agent.stop_active(),
    }


@app.post("/api/resident/message")
async def resident_message(request: ResidentMessageRequest):
    conversation_id = request.conversation_id or "default"
    audio_pcm = None
    if request.audio_base64:
        try:
            audio_pcm = base64.b64decode(request.audio_base64)
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"error": {"code": "INVALID_AUDIO_BASE64", "detail": type(exc).__name__}})
    result = await resident_agent.turn(
        text=None if audio_pcm else request.text,
        audio_pcm=audio_pcm,
        conversation_id=conversation_id,
        speak=request.speak)
    await broadcaster.send({"type": "resident.message", "correlation_id": f"res:{conversation_id}", "payload": result})
    return {"conversation_id": conversation_id, **result}


@app.post("/api/resident/run-understanding")
async def resident_run_understanding():
    result = await resident_agent.background_run(conversation_id="default", force=True)
    await broadcaster.send({"type": "resident.insight.proposed", "payload": result})
    return result


@app.get("/api/resident/messages")
async def resident_messages(conversation_id: str = "default", limit: int = Query(200, ge=1, le=1000)):
    items = store.resident_messages(conversation_id=conversation_id, limit=limit)
    return {"items": items}


@app.get("/api/resident/insights")
async def resident_insights(status: str | None = None, limit: int = Query(100, ge=1, le=500)):
    return {"items": store.understanding_insights(status=status, limit=limit)}


@app.patch("/api/resident/memory/{memory_id}")
async def resident_memory_action(memory_id: str, body: ResidentMemoryUpdateRequest):
    updated = store.resolve_resident_memory(memory_id, body.action)
    if not updated:
        raise HTTPException(status_code=404, detail={"error": {"code": "MEMORY_NOT_FOUND"}})
    await broadcaster.send({"type": "resident.memory.updated", "payload": updated})
    return updated


'''

src = src.replace(anchor, block + anchor, 1)
with open(path, "w", encoding="utf-8") as f:
    f.write(src)
print("app.py resident endpoints inserted OK")
