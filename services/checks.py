# services/checks.py
# v2.1 — locale-aware numbers/dates + refined name-typo heuristic

import regex as re
from rapidfuzz import fuzz

# ---------- Regexes ----------
NUM_RE = re.compile(r"""
    (?<!\w)                # not part of a word
    [+-]?                  # optional sign
    (?:
        \d{1,3}(?:[.,\s]\d{3})*   # 1,250 or 1.250 or 1 250
        (?:[.,]\d+)?              # optional decimals ,50 or .50
      | \d+(?:[.,]\d+)?           # plain 1250.50
    )
    (?!\w)
""", re.X)

DATE_RE = re.compile(r"""
    \b(
        \d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}     # 12/10/2025 or 12-10-2025
        | (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*
          \s+\d{1,2},?\s+\d{2,4}            # Dec 10, 2025
    )\b
""", re.I | re.X)

EXTRA_SPACE_RE = re.compile(r'\s{2,}')
DOUBLE_PUNCT_RE = re.compile(r'([!?.,:;])\1+')

# Refined name extraction helpers
TITLE = re.compile(r"^\p{Lu}\p{Ll}+$")       # Titlecase word: John, Maria
ALLCAPS = re.compile(r"^\p{Lu}{2,}$")        # Acronyms: IBM, USA
NAME_STOPWORDS = {
    # English
    "Contact", "Dear", "Attention", "Attn", "Mr", "Mrs", "Ms",
    # Common openers in a few locales (extend as needed)
    "Contacto", "Estimado", "Estimados", "Estimada", "Bonjour", "Caro", "Cara",
}

# ---------- Helpers ----------
def _normalize_amount(s: str) -> str:
    """
    Canonicalize amounts like '1,250.50' or '1.250,50' -> '1250.50'.
    Heuristic: the rightmost separator among . or , is the decimal mark.
    Currency markers are stripped first.
    """
    s = (s or "").strip().replace('\u00A0', ' ')
    s = re.sub(r'(USD|EUR|GBP|PKR|\$|€|£)\s*', '', s, flags=re.I)
    s2 = re.sub(r'[^0-9.,]', '', s)
    if not s2:
        return ''
    last_comma = s2.rfind(',')
    last_dot = s2.rfind('.')
    dec_idx = max(last_comma, last_dot)
    if dec_idx == -1:
        return re.sub(r'[.,\s]', '', s2)  # integer
    int_part = re.sub(r'[.,\s]', '', s2[:dec_idx])
    dec_part = re.sub(r'[.,\s]', '', s2[dec_idx+1:])
    return f"{int_part}.{dec_part}"

def extract_numbers_dates(text):
    """
    Extract normalized numbers and raw date strings from text.
    Avoids counting digits that are inside detected date spans.
    """
    text = text or ""
    # collect date spans to avoid double counting digits inside dates
    dates, spans = [], []
    for m in DATE_RE.finditer(text):
        dates.append(m.group(0))
        spans.append((m.start(), m.end()))

    def in_date_span(a, b):
        for s, e in spans:
            if not (b <= s or a >= e):
                return True
        return False

    raw_nums = []
    for m in NUM_RE.finditer(text):
        if in_date_span(m.start(), m.end()):
            continue
        raw_nums.append(m.group(0))

    norm_nums = [x for x in (_normalize_amount(n) for n in raw_nums) if x]
    return norm_nums, dates

def _extract_name_spans(text: str):
    """
    Return a list of person-name candidates like ['John Smith', 'Maria Lopez'].
    Heuristics:
      - group consecutive Titlecase tokens
      - require at least 2 tokens
      - ignore groups starting with common openers (Contact/Contacto/etc.)
      - ignore ALLCAPS tokens (likely org acronyms like IBM) inside the span
    """
    if not text:
        return []
    tokens = re.findall(r"\p{L}[\p{L}\-']*", text)  # words with letters/hyphen/apostrophe
    spans, cur = [], []
    for tok in tokens:
        if TITLE.match(tok):
            cur.append(tok)
        else:
            if len(cur) >= 2:
                spans.append(cur[:])
            cur = []
    if len(cur) >= 2:
        spans.append(cur[:])

    cleaned = []
    for grp in spans:
        if grp[0] in NAME_STOPWORDS:
            continue
        # Drop ALLCAPS (acronyms) but keep the 2+ Titlecase core
        grp2 = [t for t in grp if not ALLCAPS.match(t)]
        if len(grp2) >= 2:
            cleaned.append(" ".join(grp2))
    return cleaned

def name_typos(src, tgt):
    """Find likely person-name typos between src and tgt."""
    src_names = _extract_name_spans(src or "")
    tgt_names = _extract_name_spans(tgt or "")
    out = []
    for sn in src_names:
        if sn in (tgt or ""):
            continue
        best, best_score = None, 0
        for tn in tgt_names:
            sc = fuzz.ratio(sn, tn)
            if sc > best_score:
                best, best_score = tn, sc
        if best_score >= 80:
            out.append((sn, best, best_score))
    return out

# ---------- Main checks ----------
def run_checks(src_segments, tgt_segments, glossary_path=None):
    issues = []
    glossary = {}
    if glossary_path:
        try:
            import csv
            with open(glossary_path, encoding="utf-8", errors="ignore") as f:
                for row in csv.DictReader(f):
                    term = (row.get("term") or "").strip()
                    pref = (row.get("preferred_translation") or row.get("translation") or "").strip()
                    if term and pref:
                        glossary[term] = pref
        except Exception:
            # Silently skip glossary errors in MVP
            pass

    for i, (s, t) in enumerate(zip(src_segments, tgt_segments), start=1):
        # Numbers & dates
        snums, sdates = extract_numbers_dates(s)
        tnums, tdates = extract_numbers_dates(t)

        if set(snums) != set(tnums):
            issues.append({
                "type": "number_mismatch", "severity": "high", "segment": i, "src": s, "tgt": t,
                "detail": {"src": snums, "tgt": tnums}
            })

        if set(map(str.lower, sdates)) != set(map(str.lower, tdates)):
            issues.append({
                "type": "date_mismatch", "severity": "high", "segment": i, "src": s, "tgt": t,
                "detail": {"src": sdates, "tgt": tdates}
            })

        # Untranslated suspicion
        if s and t and fuzz.partial_ratio(s, t) >= 90:
            issues.append({"type": "possibly_untranslated", "severity": "medium", "segment": i, "src": s, "tgt": t})

        # Length ratio drift
        if s:
            ratio = len(t) / max(1, len(s))
            if ratio < 0.5 or ratio > 2.0:
                issues.append({
                    "type": "length_ratio", "severity": "low", "segment": i, "src": s, "tgt": t,
                    "detail": {"ratio": round(ratio, 2)}
                })

        # Orthography basics
        if t and EXTRA_SPACE_RE.search(t):
            issues.append({"type": "orthography_extra_spaces", "severity": "low", "segment": i, "src": s, "tgt": t})
        if t and DOUBLE_PUNCT_RE.search(t):
            issues.append({"type": "orthography_double_punctuation", "severity": "low", "segment": i, "src": s, "tgt": t})

        # Glossary enforcement (simple contains check)
        for term, pref in glossary.items():
            if term in (s or "") and pref and pref not in (t or ""):
                issues.append({
                    "type": "glossary_preferred_missing", "severity": "medium", "segment": i, "src": s, "tgt": t,
                    "detail": {"term": term, "preferred": pref}
                })

        # Name typo heuristic
        for (orig_name, tgt_name, score) in name_typos(s, t):
            issues.append({
                "type": "name_possible_typo", "severity": "medium", "segment": i, "src": s, "tgt": t,
                "detail": {"source_name": orig_name, "target_near": tgt_name, "score": score}
            })

    summary = {
        "high": sum(1 for x in issues if x["severity"] == "high"),
        "medium": sum(1 for x in issues if x["severity"] == "medium"),
        "low": sum(1 for x in issues if x["severity"] == "low"),
        "segments": len(src_segments)
    }
    return {"summary": summary, "issues": issues}
