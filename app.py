# app.py
from flask import Flask, render_template, request, jsonify, send_from_directory
import os, uuid, json, threading
from werkzeug.utils import secure_filename

from services.extract import to_text
from services.align import simple_align
from services.checks import run_checks as run_checks_python
from services.llm import run_checks_llm
from services.annotate import build_annotated_docx, save_plain_docx

app = Flask(__name__)

# --- Config ---
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB
UPLOAD_ROOT = "/tmp/translation-checker" if os.path.isdir("/tmp") else "runs"
os.makedirs(UPLOAD_ROOT, exist_ok=True)
ALLOWED = {".txt", ".docx", ".pdf"}

def _ext_ok(name): 
    return os.path.splitext(name or "")[1].lower() in ALLOWED

@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "File too large (max 100MB)."}), 413

@app.get("/")
def index():
    return render_template("index.html")

# ---------- PROGRESS INFRA ----------
def _write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def _write_progress(run_dir, percent, status="working"):
    _write_json(os.path.join(run_dir, "progress.json"), {"percent": int(percent), "status": status})

def _read_json(path, default=None):
    if not os.path.exists(path): 
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def _analyze_job(run_dir, mode, opath, tpath):
    try:
        _write_progress(run_dir, 1, "extracting")
        src_text = to_text(opath)
        tgt_text = to_text(tpath)
        if not src_text.strip() or not tgt_text.strip():
            _write_progress(run_dir, 100, "error: Could not read text from one of the files")
            return

        _write_progress(run_dir, 10, "aligning")
        src_segments, tgt_segments = simple_align(src_text, tgt_text)
        _write_json(os.path.join(run_dir, "segments.json"), {"src": src_segments, "tgt": tgt_segments})

        # ANALYZE
        if mode == "chatgpt":
            key_path = os.path.join(os.path.dirname(__file__), "local_openai_key.txt")
            if not os.path.exists(key_path):
                _write_progress(run_dir, 100, "error: local_openai_key.txt missing")
                return
            with open(key_path, "r", encoding="utf-8") as f:
                api_key = f.read().strip()
            _write_progress(run_dir, 40, "analyzing (LLM)")
            results = run_checks_llm(src_segments, tgt_segments, api_key)
        else:
            issues = []
            n = len(src_segments)
            chunk = max(1, n // 10)  # 10 chunks
            _write_progress(run_dir, 20, "analyzing")
            for i in range(0, n, chunk):
                part = run_checks_python(src_segments[i:i+chunk], tgt_segments[i:i+chunk])
                # shift segment index
                for it in part["issues"]:
                    it["segment"] += i
                issues.extend(part["issues"])
                pct = 20 + int(min(70, (i+chunk) / max(1, n) * 70))  # 20..90
                _write_progress(run_dir, pct, f"analyzing {min(100, int((i+chunk)/max(1,n)*100))}%")
            results = {
                "summary": {
                    "high": sum(1 for x in issues if x["severity"]=="high"),
                    "medium": sum(1 for x in issues if x["severity"]=="medium"),
                    "low": sum(1 for x in issues if x["severity"]=="low"),
                    "segments": len(src_segments)
                },
                "issues": issues
            }

        _write_json(os.path.join(run_dir, "results.json"), results)

        # annotated copy
        _write_progress(run_dir, 92, "building annotated doc")
        build_annotated_docx(
            translation_segments=tgt_segments,
            issues=results.get("issues", []),
            out_path=os.path.join(run_dir, "translation_annotated.docx")
        )

        _write_progress(run_dir, 100, "done")
    except Exception as e:
        _write_progress(run_dir, 100, f"error: {type(e).__name__}: {e}")

@app.post("/start")
def start_job():
    try:
        if "original" not in request.files or "translation" not in request.files:
            return jsonify({"error": "Upload both files (original & translation)."}), 400
        mode = request.form.get("mode", "python")
        orig = request.files["original"]
        tran = request.files["translation"]
        if not orig.filename or not tran.filename:
            return jsonify({"error": "Choose both files before submitting."}), 400
        if not _ext_ok(orig.filename) or not _ext_ok(tran.filename):
            return jsonify({"error": "Supported types: .txt, .docx, .pdf"}), 400

        run_id = str(uuid.uuid4())
        run_dir = os.path.join(UPLOAD_ROOT, run_id)
        os.makedirs(run_dir, exist_ok=True)

        opath = os.path.join(run_dir, secure_filename(orig.filename))
        tpath = os.path.join(run_dir, secure_filename(tran.filename))
        orig.save(opath)
        tran.save(tpath)

        _write_progress(run_dir, 0, "queued")
        _write_json(os.path.join(run_dir, "meta.json"), {"mode": mode})

        th = threading.Thread(target=_analyze_job, args=(run_dir, mode, opath, tpath), daemon=True)
        th.start()
        return jsonify({"run_id": run_id})
    except Exception as e:
        return jsonify({"error": f"Start failed: {type(e).__name__}: {str(e)}"}), 500

@app.get("/progress/<run_id>")
def progress(run_id):
    run_dir = os.path.join(UPLOAD_ROOT, run_id)
    pr = _read_json(os.path.join(run_dir, "progress.json"), {"percent": 0, "status": "queued"})
    return jsonify(pr)

@app.get("/result/<run_id>")
def result(run_id):
    run_dir = os.path.join(UPLOAD_ROOT, run_id)
    results = _read_json(os.path.join(run_dir, "results.json"), {})
    if not results:
        return jsonify({"error": "Results not ready"}), 404
    return jsonify({
        "summary": results.get("summary", {}),
        "issues": results.get("issues", []),
        "download": f"/download/{run_id}/translation_annotated.docx",
        "edit_url": f"/edit/{run_id}"
    })

# ---------- Existing editor routes ----------
@app.get("/edit/<run_id>")
def edit(run_id):
    run_dir = os.path.join(UPLOAD_ROOT, run_id)
    if not os.path.exists(os.path.join(run_dir, "segments.json")):
        return "Run not found", 404
    return render_template("edit.html", run_id=run_id)

@app.get("/data/<run_id>")
def data_for_edit(run_id):
    run_dir = os.path.join(UPLOAD_ROOT, run_id)
    segp = os.path.join(run_dir, "segments.json")
    resp = os.path.join(run_dir, "results.json")
    if not os.path.exists(segp) or not os.path.exists(resp):
        return jsonify({"error": "Run not found"}), 404
    with open(segp, encoding="utf-8") as f:
        segs = json.load(f)
    with open(resp, encoding="utf-8") as f:
        results = json.load(f)
    return jsonify({"segments": segs, "results": results})

@app.post("/save/<run_id>")
def save_edited(run_id):
    try:
        payload = request.get_json(silent=True) or {}
        edited = payload.get("tgt_segments") or []
        if not isinstance(edited, list):
            return jsonify({"error": "Invalid payload: tgt_segments must be a list"}), 400
        run_dir = os.path.join(UPLOAD_ROOT, run_id)
        if not os.path.isdir(run_dir):
            return jsonify({"error": "Run not found"}), 404
        out_name = "translation_fixed.docx"
        out_path = os.path.join(run_dir, out_name)
        save_plain_docx(edited, out_path)
        with open(os.path.join(run_dir, "segments-edited.json"), "w", encoding="utf-8") as f:
            json.dump({"tgt": edited}, f, ensure_ascii=False, indent=2)
        return jsonify({"ok": True, "download": f"/download/{run_id}/{out_name}"})
    except Exception as e:
        return jsonify({"error": f"Save failed: {type(e).__name__}: {str(e)}"}), 500

@app.get("/download/<run_id>/<filename>")
def download(run_id, filename):
    run_dir = os.path.join(UPLOAD_ROOT, run_id)
    if not os.path.exists(os.path.join(run_dir, filename)):
        return "File not found", 404
    return send_from_directory(run_dir, filename, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
