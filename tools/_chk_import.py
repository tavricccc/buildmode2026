import sys
sys.path.insert(0, "D:/Longcare")
import backend.app as a
print("app import OK")
print("tts_configured =", a.resident_agent.tts_configured)
routes = sorted({r.path for r in a.app.routes if hasattr(r, "path") and r.path.startswith("/api/resident")})
print("resident routes:", routes)
