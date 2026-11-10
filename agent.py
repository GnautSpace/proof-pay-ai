import json, hashlib, math
from llm import ask

def split_chunks(text: str, n: int):
    words = text.split()
    size = max(1, math.ceil(len(words) / n))
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)][:n]

def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()

def _parse_json(raw: str):
    try:
        return json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except Exception:
        return {}

def run_worker(chunk: str, sabotage: bool = False):
    """Simulated compute node: returns (output, claimed_hash)."""
    if sabotage:
        out = {"summary": "lorem ipsum", "key_terms": []}  # cheating worker
    else:
        raw = ask(
            'Summarize the text in at most 2 sentences and give exactly 3 key terms. '
            'Reply ONLY with JSON: {"summary": "...", "key_terms": ["a","b","c"]}\n\n' + chunk)
        out = _parse_json(raw)
    return out, _digest(out)

def verify(chunk: str, out: dict, claimed_hash: str, use_judge: bool = False, rules: dict = None) -> dict:
    rules = rules or {}
    max_chars = rules.get("max_summary_chars", 500)
    min_grounded = rules.get("min_grounded_terms", 2)
    banned = [w.strip().lower() for w in rules.get("banned_words", []) if w.strip()]

    schema = (isinstance(out, dict) and isinstance(out.get("summary"), str)
              and isinstance(out.get("key_terms"), list) and len(out["key_terms"]) == 3)
    checks = {
        "schema": schema,
        "hash_match": _digest(out) == claimed_hash,
        "length_ok": bool(schema and 10 < len(out["summary"]) <= max_chars),
    }
    if schema:
        text = chunk.lower()
        hits = sum(1 for t in out["key_terms"] if isinstance(t, str) and t.lower() in text)
        checks["grounded"] = hits >= min_grounded
        summary = out["summary"].lower()
        checks["no_banned_words"] = not any(b in summary for b in banned)
    else:
        checks["grounded"] = False
        checks["no_banned_words"] = False
    if use_judge:
        if schema:
            verdict = ask(f"TEXT:\n{chunk}\n\nSUMMARY:\n{out['summary']}\n\n"
                          "Is the summary faithful to the text? Answer only YES or NO.", 5)
            checks["ai_judge"] = verdict.strip().upper().startswith("YES")
        else:
            checks["ai_judge"] = False
    return checks
