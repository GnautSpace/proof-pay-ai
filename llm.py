import os
from google import genai

_client = None
_models = None
_dead = set()

SKIP = ("image", "tts", "live", "audio", "embedding", "robotics", "computer", "vision")

def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client

def _candidate_models():
    global _models
    if _models is None:
        names = []
        try:
            for m in _get_client().models.list():
                actions = getattr(m, "supported_actions", None) or []
                n = m.name.replace("models/", "")
                if "generateContent" in actions and "flash" in n and not any(s in n for s in SKIP):
                    names.append(n)
        except Exception:
            pass
        names.sort(reverse=True)   # newest-looking names first
        _models = names or ["gemini-3.8-flash", "gemini-2.5-flash"]
    return _models

def ask(prompt: str, max_tokens: int = 400) -> str:
    errors = []
    for model in _candidate_models():
        if model in _dead:
            continue
        try:
            resp = _get_client().models.generate_content(model=model, contents=prompt)
            return resp.text or ""
        except Exception as e:
            msg = str(e)
            if "404" in msg or "NOT_FOUND" in msg:
                _dead.add(model)
            errors.append(f"{model}: {msg[:90]}")
    raise RuntimeError("All Gemini models failed:\n" + "\n".join(errors))
