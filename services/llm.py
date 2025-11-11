from typing import List, Dict, Any
from tenacity import retry, wait_exponential, stop_after_attempt, RetryError
from openai import OpenAI
from openai import APIConnectionError, AuthenticationError, RateLimitError, BadRequestError
import json

SCHEMA_HINT = (
    "Return ONLY JSON with this shape:\n"
    "{\n"
    '  "issues": [\n'
    "    {\n"
    '      "segment": <int>,\n'
    '      "type": "number_error|date_error|name_error|terminology|omission|addition|mistranslation|orthography|punctuation|formatting|other",\n'
    '      "severity": "high|medium|low",\n'
    '      "evidence": "<string>",\n'
    '      "suggestion": "<string, optional>"\n'
    "    }\n"
    "  ]\n"
    "}\n"
)

SYSTEM = (
    "You are a meticulous bilingual translation QA engine. "
    "Compare source and target segments and report translation issues. "
    "Be strict with numbers/dates/names/terminology; do not invent issues. "
    + SCHEMA_HINT
)

def _prompt(batch: List[Dict[str, Any]]) -> str:
    lines = ["Evaluate the following aligned segments.",
             "If a segment is fine, do not add an issue for it.",
             "", "Segments:"]
    for item in batch:
        i = item["segment"]; s = item["src"].strip(); t = item["tgt"].strip()
        lines.append(f"[{i}] SRC: {s}")
        lines.append(f"[{i}] TGT: {t}")
    return "\n".join(lines)

def _to_text(resp) -> str:
    txt = getattr(resp, "output_text", None)
    if txt:
        return txt
    try:
        parts = []
        for item in getattr(resp, "output", []) or []:
            for c in getattr(item, "content", []) or []:
                if getattr(c, "type", "") == "output_text":
                    parts.append(getattr(c, "text", ""))
        return "".join(parts) if parts else ""
    except Exception:
        return ""

def _try_load_json(s: str) -> dict:
    s = (s or "").strip()
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        pass
    try:
        start = s.find("{"); end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(s[start:end+1])
    except Exception:
        return {}

@retry(wait=wait_exponential(min=1, max=6), stop=stop_after_attempt(2))
def _call(client: OpenAI, model: str, prompt: str):
    resp = client.responses.create(
        model=model,
        input=[{"role": "system", "content": SYSTEM},
               {"role": "user", "content": prompt}],
    )
    return _try_load_json(_to_text(resp)) or {"issues": []}

def run_checks_llm(src_segments: List[str], tgt_segments: List[str], api_key: str, model: str = "gpt-4o-mini"):
    # Key sanity checks
    if not api_key or not api_key.strip():
        raise ValueError("ChatGPT mode: API key file is empty.")
    stripped = api_key.strip()
    if "\n" in stripped or "\r" in stripped or " " in stripped:
        raise ValueError("ChatGPT mode: API key must be a single line with no spaces/newlines.")
    if not stripped.startswith(("sk-", "sk-proj-", "sk-or-")):
        raise ValueError("ChatGPT mode: API key format looks wrong. It should start with 'sk-' (or 'sk-proj-').")

    try:
        client = OpenAI(api_key=stripped, timeout=30.0)
        issues = []
        batch = []
        BATCH = 8
        for idx, (s, t) in enumerate(zip(src_segments, tgt_segments), start=1):
            batch.append({"segment": idx, "src": s, "tgt": t})
            if len(batch) == BATCH:
                data = _call(client, model, _prompt(batch)) or {}
                issues.extend(data.get("issues", []))
                batch = []
        if batch:
            data = _call(client, model, _prompt(batch)) or {}
            issues.extend(data.get("issues", []))

    except AuthenticationError as e:
        raise ValueError("ChatGPT mode: Authentication failed. Check your API key.") from e
    except RateLimitError as e:
        raise ValueError("ChatGPT mode: Rate limit reached. Try again later.") from e
    except APIConnectionError as e:
        raise ValueError("ChatGPT mode: Network connection error. Check internet/firewall.") from e
    except BadRequestError as e:
        raise ValueError(f"ChatGPT mode: Bad request to API (possibly model not enabled). {e}") from e
    except RetryError as e:
        last = e.last_attempt.exception() if hasattr(e, "last_attempt") else None
        raise ValueError(f"ChatGPT mode: API call retried and failed. Root cause: {last}") from e
    except Exception as e:
        raise ValueError(f"ChatGPT mode: Unexpected error: {e}") from e

    # Normalize
    norm = []
    for it in issues:
        seg = it.get("segment", 0)
        typ = it.get("type", "other")
        sev = it.get("severity", "low")
        detail = {"evidence": it.get("evidence", "")}
        if it.get("suggestion"):
            detail["suggestion"] = it["suggestion"]
        norm.append({
            "type": f"llm_{typ}",
            "severity": sev,
            "segment": seg,
            "src": src_segments[seg-1] if 0 <= seg-1 < len(src_segments) else "",
            "tgt": tgt_segments[seg-1] if 0 <= seg-1 < len(tgt_segments) else "",
            "detail": detail
        })

    summary = {
        "high": sum(1 for x in norm if x["severity"] == "high"),
        "medium": sum(1 for x in norm if x["severity"] == "medium"),
        "low": sum(1 for x in norm if x["severity"] == "low"),
        "segments": len(src_segments)
    }
    return {"summary": summary, "issues": norm}
