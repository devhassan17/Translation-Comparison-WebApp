# services/align.py
import regex as re

SPLIT_RE = re.compile(r'(?<=[.!?。؟])\s+')

def split_sentences(text):
    if not text:
        return []
    parts = SPLIT_RE.split(text.strip())
    return [p for p in parts if p and p.strip()]

def simple_align(src, tgt):
    s = split_sentences(src)
    t = split_sentences(tgt)
    n = max(len(s), len(t))
    s += [""] * (n - len(s))
    t += [""] * (n - len(t))
    return s, t
