import os
from docx import Document

# Optional PDF extraction via pdfplumber
def _try_pdf(path):
    try:
        import pdfplumber
    except Exception:
        return ""  # pdfplumber not installed
    try:
        text_parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                text_parts.append(t)
        return "\n".join(text_parts)
    except Exception:
        return ""

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
    if ext == ".pdf":
        t = _try_pdf(path)
        if t.strip():
            return t
        # fallbacks
        t = _try_docx(path)
        return t if t.strip() else _try_txt(path)
    if ext == ".docx":
        t = _try_docx(path)
        if t.strip():
            return t
        return _try_txt(path)
    # default .txt (or unknown → try txt then docx then pdf)
    t = _try_txt(path)
    if t.strip():
        return t
    t = _try_docx(path)
    if t.strip():
        return t
    return _try_pdf(path)
