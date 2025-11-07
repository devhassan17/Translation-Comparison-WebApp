# Translation Checker (MVP)

Flask app to compare an original document and its translation and flag likely issues (numbers/dates mismatches, untranslated chunks, orthography basics, and optional glossary checks).

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
# open http://127.0.0.1:5000
```

## Features (MVP)
- Upload Original + Translation (TXT/DOCX)
- Checks:
  - Number/date mismatches (high severity)
  - Possibly untranslated segments via fuzzy match (medium)
  - Length ratio drift (low)
  - Orthography basics: double punctuation, extra spaces (low)
  - Optional glossary CSV: `term,preferred_translation`
- HTML results and per-run report page

## Structure
```
translation-checker-mvp/
  app.py
  requirements.txt
  /runs/
  /services/
    extract.py
    align.py
    checks.py
  /static/
    app.js
    styles.css
  /templates/
    index.html
    report.html
  /samples/
    original.txt
    translation.txt
    glossary.csv
```

## v2 Updates
- Locale-aware number normalization (1,250.50 == 1.250,50)
- Prevents double-counting numbers inside dates
- Simple name-typo heuristic
