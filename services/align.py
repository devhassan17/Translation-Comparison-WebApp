import regex as re

_SPLIT = re.compile(r"[\.!?]+[\s]+|\n+", re.M)

def _split(text: str):
    text = text or ""
    parts = [p.strip() for p in _SPLIT.split(text) if p.strip()]
    return parts if parts else [text.strip()]

def simple_align(src_text: str, tgt_text: str):
    s = _split(src_text)
    t = _split(tgt_text)
    n = max(len(s), len(t))
    s += [""] * (n - len(s))
    t += [""] * (n - len(t))
    return s, t
