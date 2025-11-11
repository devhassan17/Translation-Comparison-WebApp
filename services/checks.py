import regex as re
import unicodedata
from rapidfuzz import fuzz
from dateparser.search import search_dates

NUM_RE = re.compile(r"(?<!\w)[+-]?(?:\d{1,3}(?:[.,\s\u00A0]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(?!\w)", re.X)
EXTRA_SPACE_RE = re.compile(r'(?:\s|\u00A0){2,}')
DOUBLE_PUNCT_RE = re.compile(r'([!?.,:;])\1+')
TITLE = re.compile(r"^\p{Lu}\p{Ll}+$")
ALLCAPS = re.compile(r"^\p{Lu}{2,}$")

# English, Spanish, French, German, Italian, Portuguese, Turkish, Arabic (common variants)
MONTH_WORD_RE = re.compile(
    r"\b(?:"
    # En
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
    r"january|february|march|april|june|july|august|september|october|november|december|"
    # Es
    r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|"
    # Fr
    r"janvier|février|fevrier|mars|avril|mai|juin|juillet|août|aout|septembre|octobre|novembre|décembre|decembre|"
    # De
    r"jan|feb|mär|maer|apr|mai|jun|jul|aug|sep|okt|nov|dez|"
    r"januar|februar|märz|maerz|april|mai|juni|juli|august|september|oktober|november|dezember|"
    # It
    r"gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre|"
    # Pt
    r"janeiro|fevereiro|março|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|"
    # Tr
    r"ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik|"
    # Ar
    r"يناير|فبراير|مارس|أبريل|ابريل|مايو|يونيو|يوليو|أغسطس|اغسطس|سبتمبر|أكتوبر|اكتوبر|نوفمبر|ديسمبر"
    r")\b",
    re.I
)

def normalize_digits(text: str) -> str:
    if not text:
        return ""
    out = []
    for ch in text:
        try:
            if unicodedata.category(ch) == "Nd":
                out.append(str(unicodedata.digit(ch)))
            else:
                out.append(ch)
        except Exception:
            out.append(ch)
    return "".join(out)

def _normalize_amount(s: str) -> str:
    s = normalize_digits((s or "").strip()).replace('\u00A0', ' ')
    s = re.sub(r'(USD|EUR|GBP|PKR|AUD|CAD|JPY|CNY|INR|SAR|AED|\$|€|£|¥|₹)\s*', '', s, flags=re.I)
    s2 = re.sub(r'[^0-9.,]', '', s)
    if not s2:
        return ''
    last_comma = s2.rfind(',')
    last_dot = s2.rfind('.')
    dec_idx = max(last_comma, last_dot)
    if dec_idx == -1:
        return re.sub(r'[.,\s]', '', s2)
    int_part = re.sub(r'[.,\s]', '', s2[:dec_idx])
    dec_part = re.sub(r'[.,\s]', '', s2[dec_idx+1:])
    return int_part + '.' + dec_part

def _looks_like_numeric_date(raw: str) -> bool:
    s = raw.strip()
    if re.match(r"^\d{1,2}([/\-.])\d{1,2}\1\d{4}$", s):  # dd/mm/yyyy
        return True
    if re.match(r"^\d{4}([\-\.])\d{1,2}\1\d{1,2}$", s):  # yyyy-mm-dd
        return True
    return False

def _has_month_word(ctx: str) -> bool:
    return bool(MONTH_WORD_RE.search(ctx))

def _find_dates_any_language(text_norm: str):
    """
    Use dateparser.search_dates with strong filtering:
    - Keep if a month word is nearby, or a clean numeric date pattern.
    - Reject matches containing '%' to avoid 19,6% → 2025-06-19.
    """
    raw_dates, spans, iso_dates = [], [], []
    settings = {
        "PREFER_DAY_OF_MONTH": "first",
        "PREFER_DATES_FROM": "past",
        "RETURN_AS_TIMEZONE_AWARE": False,
        "DATE_ORDER": "DMY",
    }
    try:
        results = search_dates(text_norm, settings=settings, add_detected_language=True)
    except Exception:
        return raw_dates, spans, iso_dates
    if not results:
        return raw_dates, spans, iso_dates

    def to_iso(dt):
        try:
            return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"
        except Exception:
            return None

    cursor = 0
    for item in results:
        raw, dt = item[0], item[1]
        raw = str(raw)

        # Reject percent contexts outright
        if "%" in raw:
            continue

        start = text_norm.find(raw, cursor)
        if start == -1:
            start = text_norm.find(raw)
            if start == -1:
                continue
        end = start + len(raw)
        left = max(0, start - 15)
        right = min(len(text_norm), end + 15)

        month_near = _has_month_word(text_norm[left:right])
        has_letters = bool(re.search(r"\p{L}", raw))
        numeric_ok = _looks_like_numeric_date(raw)

        if not (month_near or numeric_ok):
            continue

        iso = to_iso(dt)
        if not iso:
            continue

        # avoid nesting overlaps
        if any(start >= s and end <= e for s, e in spans):
            continue

        raw_dates.append(raw)
        spans.append((start, end))
        iso_dates.append(iso)
        cursor = end

    return raw_dates, spans, iso_dates

def extract_numbers_dates(text):
    text_norm = normalize_digits(text or "")
    _raw_dates, spans, norm_dates = _find_dates_any_language(text_norm)

    def in_date_span(a, b):
        for s, e in spans:
            if not (b <= s or a >= e):
                return True
        return False

    raw_nums = [m.group(0) for m in NUM_RE.finditer(text_norm) if not in_date_span(m.start(), m.end())]
    norm_nums = [x for x in (_normalize_amount(n) for n in raw_nums) if x]
    return norm_nums, norm_dates

def _extract_name_spans(text: str):
    if not text:
        return []
    tokens = re.findall(r"\p{L}[\p{L}\-']*", text)
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
        grp2 = [t for t in grp if not ALLCAPS.match(t)]
        if len(grp2) >= 2:
            cleaned.append(" ".join(grp2))
    return cleaned

def name_typos(src, tgt):
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

def run_checks(src_segments, tgt_segments):
    issues = []
    for i, (s, t) in enumerate(zip(src_segments, tgt_segments), start=1):
        snums, sdates = extract_numbers_dates(s)
        tnums, tdates = extract_numbers_dates(t)

        if set(snums) != set(tnums):
            issues.append({"type": "number_mismatch", "severity": "high", "segment": i, "src": s, "tgt": t,
                           "detail": {"src": snums, "tgt": tnums}})
        if set(sdates) != set(tdates):
            issues.append({"type": "date_mismatch", "severity": "high", "segment": i, "src": s, "tgt": t,
                           "detail": {"src": sdates, "tgt": tdates}})

        if s and t and fuzz.partial_ratio(s, t) >= 90:
            issues.append({"type": "possibly_untranslated", "severity": "medium", "segment": i, "src": s, "tgt": t})

        if s:
            ratio = len(t) / max(1, len(s))
            if ratio < 0.5 or ratio > 2.0:
                issues.append({"type": "length_ratio", "severity": "low", "segment": i, "src": s, "tgt": t,
                               "detail": {"ratio": round(ratio, 2)}})

        if t and EXTRA_SPACE_RE.search(t):
            issues.append({"type": "orthography_extra_spaces", "severity": "low", "segment": i, "src": s, "tgt": t})
        if t and DOUBLE_PUNCT_RE.search(t):
            issues.append({"type": "orthography_double_punctuation", "severity": "low", "segment": i, "src": s, "tgt": t})

        for (orig_name, tgt_name, score) in name_typos(s, t):
            issues.append({"type": "name_possible_typo", "severity": "medium", "segment": i, "src": s, "tgt": t,
                           "detail": {"source_name": orig_name, "target_near": tgt_name, "score": score}})

    summary = {
        "high": sum(1 for x in issues if x["severity"] == "high"),
        "medium": sum(1 for x in issues if x["severity"] == "medium"),
        "low": sum(1 for x in issues if x["severity"] == "low"),
        "segments": len(src_segments),
    }
    return {"summary": summary, "issues": issues}
