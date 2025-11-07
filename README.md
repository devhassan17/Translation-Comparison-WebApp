# Translation QA — Two Uploads (Python vs ChatGPT)

Two-file upload only (Original & Translation). Choose analysis mode:
- **Python modules (offline)**: deterministic checks (numbers, dates, length, spacing, name-typo).
- **ChatGPT (API)**: context-aware review (mistranslation, omissions/additions, terminology, suggestions).

## ChatGPT local key
Create **local_openai_key.txt** next to `app.py` with your API key on a single line. This file is not uploaded; it stays with you.

## Run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
# open http://127.0.0.1:5000
```

## Deploy
Start command:
```
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120
```
