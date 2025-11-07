# services/checks.py
# v3 — language-agnostic dates via dateparser + all-Unicode digit normalization
#      locale-agnostic number normalization + refined name-typo heuristic

import regex as re
import unicodedata
from rapidfuzz import fuzz
from dateparser.search import search_dates

# ---------- All-Unicode digit normalization ----------
def normalize_digits(text: str) -> str:
    """
    Convert any Unicode decimal digit (category Nd) to ASCII 0-9.
    Works for Arabic-Indic, Persian, Devanagari, etc.
    """
    if not text:
        return ""
    out = []
    for ch in text:
        try:
            if unicodedata.category(ch) == "Nd":
                out.append(str(unicodedata.digit(ch)))
            else:
                out.append(ch)
        except (TypeError, ValueError):
            out.append(ch)
    return "".join(out)

# ---------- Regexes ----------
NUM_RE = re.compile(r"""
    (?<!\w)                # not part of a word
    [+-]?                  # optional sign
    (?:
        \d{1,3}(?:[.,\s\u00A0]\d{3})*   # 1,250 or 1.250 or 1 250 or 1 250
        (?:[.,]\d+)?                    # optional decimals ,50 or .50
      | \d+(?:[.,]\d+)?                 # plain 1250.50
    )
    (?!\w)
""", re.X)

EXTRA_SPACE_RE = re.compile(r'(?:\s|\u00A0){2,}')
DOUBLE_PUNCT_RE = re.compile(r'([!?.,:;])\1+')

# Refined name extraction (best for cased scripts; still harmless for others)
TITLE = re.compile(r"^\p{Lu}\p{Ll}+$")       # Titlecase word: John, Maria
ALLCAPS = re.compile(r"^\p{Lu}{2,}$")        # Acronyms: IBM, USA
NAME_STOPWORDS = {
    "Contact", "Dear", "Attention", "Attn", "Mr", "Mrs", "Ms",
    "Contacto", "Estimado", "Estimados", "Estimada", "Bonjour", "Caro", "Cara",
}

# ---------- Numbers ----------
def _normalize_amount(s: str) -> str:
    """
    Canonicalize amounts like '1,250.50', '1.250,50', '1 250,50' -> '1250.50'.
    Heuristic: the rightmost separator among . or , is the decimal mark.
    Strips common currency markers.
    """
    s = normalize_digits((s or "").strip()).replace('\u00A0', ' ')
    s = re.sub(r'(USD|EUR|GBP|PKR|AUD|CAD|JPY|CNY|INR|SAR|AED|\$|€|£|¥|₹)\s*', '', s, flags=re.I)
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

# ---------- Dates (language-agnostic via dateparser) ----------
def _find_dates_any_language(text_norm: str):
    """
    Use dateparser to find dates in any language/script. Returns:
      raw_dates: list of matched substrings,
      spans: list of (start, end) indexes,
      iso_dates: list of YYYY-MM-DD strings
    """
    raw_dates, spans, iso_dates = [], [], []
    # settings: don't try future bias, prefer detecting both MDY/DMY; keep timezone-naive
    results = search_dates(
        text_norm,
        settings={
            "PREFER_DAY_OF_MONTH": "first",
            "PREFER_DATES_FROM": "past",
            "RETURN_AS_TIMEZONE_AWARE": False,
            "RELATIVE_BASE": None,
            # allow both orders; dateparser will infer using language cues & separators
            "DATE_ORDER": "DMY",
        },
        add_detected_language=True,  # returns tuples (text, dt, lang)
    )

    if not results:
        return raw_dates, spans, iso_dates

    # Walk through results and deduplicate overlapping matches by keeping longest
    # Convert dt to ISO (date only)
    # results format: [(matched_text, datetime, lang), ...] depending on version
    # dateparser may return [(text, dt), ...] without lang; handle both
    def to_iso(dt):
        try:
            return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"
        except Exception:
            return None

    used = []
    idx = 0
    cursor = 0
    text_len = len(text_norm)

    # To get spans, re-search occurrences of each raw substring sequentially
    for item in results:
        if len(item) == 3:
            raw, dt, _lang = item
        else:
            raw, dt = item
        raw = str(raw)
        # find next occurrence of raw starting at cursor to avoid earlier duplicates
        start = text_norm.find(raw, cursor)
        if start == -1:
            # fallback: global search
            start = text_norm.find(raw)
            if start == -1:
                continue
        end = start + len(raw)
        cursor = end  # move cursor forward

        iso = to_iso(dt)
        if not iso:
            continue

        # deduplicate overlaps: drop if fully inside an existing span
        overlapped = False
        for s, e in spans:
            if start >= s and end <= e:
                overlapped = True
                break
        if overlapped:
            continue

        raw_dates.append(raw)
        spans.append((start, end))
        iso_dates.append(iso)

    return raw_dates, spans, iso_dates

def extract_numbers_dates(text):
    """
    Extract normalized numbers and normalized dates (ISO).
    - Normalizes all Unicode digits to ASCII
    - Finds dates in any language using dateparser
    - Skips numbers that fall inside date spans
    """
    text_norm = normalize_digits(text or "")

    _raw_dates, spans, norm_dates = _find_dates_any_language(text_norm)

    def in_date_span(a, b):
        for s, e in spans:
            if not (b <= s or a >= e):
                return True
        return False

    raw_nums = []
    for m in NUM_RE.finditer(text_norm):
        if in_date_span(m.start(), m.end()):
            continue
        raw_nums.append(m.group(0))

    norm_nums = [x for x in (_normalize_amount(n) for n in raw_nums) if x]
    return norm_nums, norm_dates

# ---------- Names (lightweight heuristic) ----------
def _extract_name_spans(text: str):
    """
    Return a list of person-name candidates like ['John Smith', 'Maria Lopez'].
    Works best for cased scripts; harmless no-op fallback for others.
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
            pass  # MVP: ignore glossary read failures

    for i, (s, t) in enumerate(zip(src_segments, tgt_segments), start=1):
        # Numbers & Dates (language-agnostic)
        snums, sdates = extract_numbers_dates(s)
        tnums, tdates = extract_numbers_dates(t)

        if set(snums) != set(tnums):
            issues.append({
                "type": "number_mismatch", "severity": "high", "segment": i, "src": s, "tgt": t,
                "detail": {"src": snums, "tgt": tnums}
            })

        # sdates/tdates already ISO (YYYY-MM-DD)
        if set(sdates) != set(tdates):
            issues.append({
                "type": "date_mismatch", "severity": "high", "segment": i, "src": s, "tgt": t,
                "detail": {"src": sdates, "tgt": tdates}
            })

        # Untranslated suspicion
        if s and t and fuzz.partial_ratio(s, t) >= 90:
            issues.append({"type": "possibly_untranslated", "severity": "medium",
                           "segment": i, "src": s, "tgt": t})

        # Length ratio drift
        if s:
            ratio = len(t) / max(1, len(s))
            if ratio < 0.5 or ratio > 2.0:
                issues.append({"type": "length_ratio", "severity": "low",
                               "segment": i, "src": s, "tgt": t,
                               "detail": {"ratio": round(ratio, 2)}})

        # Orthography basics
        if t and EXTRA_SPACE_RE.search(t):
            issues.append({"type": "orthography_extra_spaces", "severity": "low",
                           "segment": i, "src": s, "tgt": t})
        if t and DOUBLE_PUNCT_RE.search(t):
            issues.append({"type": "orthography_double_punctuation", "severity": "low",
                           "segment": i, "src": s, "tgt": t})

        # Glossary enforcement (simple contains check)
        for term, pref in glossary.items():
            if term in (s or "") and pref and pref not in (t or ""):
                issues.append({"type": "glossary_preferred_missing", "severity": "medium",
                               "segment": i, "src": s, "tgt": t,
                               "detail": {"term": term, "preferred": pref}})

        # Name typo heuristic
        for (orig_name, tgt_name, score) in name_typos(s, t):
            issues.append({"type": "name_possible_typo", "severity": "medium",
                           "segment": i, "src": s, "tgt": t,
                           "detail": {"source_name": orig_name, "target_near": tgt_name, "score": score}})

    summary = {
        "high": sum(1 for x in issues if x["severity"] == "high"),
        "medium": sum(1 for x in issues if x["severity"] == "medium"),
        "low": sum(1 for x in issues if x["severity"] == "low"),
        "segments": len(src_segments),
    }
    return {"summary": summary, "issues": issues}
