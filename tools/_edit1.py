p = "D:/Longcare/backend/schemas.py"
with open(p, encoding="utf-8") as f:
    m = f.read()
needle = "    speak: bool = True\n"
add = ("    speak: bool = True\n"
       "    audio_base64: str | None = Field(default=None, max_length=2_000_000)\n"
       "    asr_only: bool = False\n")
assert needle in m, "speak line not found"
assert "audio_base64" not in m, "already patched"
m = m.replace(needle, add, 1)
with open(p, "w", encoding="utf-8") as f:
    f.write(m)
print("schemas.py patched OK")
