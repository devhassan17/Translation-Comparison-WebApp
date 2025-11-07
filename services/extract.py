from docx import Document
import os

def _try_txt(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def _try_docx(path):
    try:
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        return ""

def to_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        t = _try_docx(path)
        if t.strip():
            return t
        return _try_txt(path)
    t = _try_txt(path)
    if t.strip():
        return t
    return _try_docx(path)
