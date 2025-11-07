# services/extract.py
from docx import Document
import os

def _txt(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def _docx(path):
    try:
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        return ""

def to_text(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ""):
        return _txt(path)
    if ext == ".docx":
        return _docx(path)
    # fallback to plain read
    try:
        return _txt(path)
    except Exception:
        return ""
