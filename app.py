from flask import Flask, render_template, request, jsonify
import os, uuid, json
from werkzeug.utils import secure_filename
from services.extract import to_text
from services.align import simple_align
from services.checks import run_checks as run_checks_python
from services.llm import run_checks_llm

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20MB
UPLOAD_ROOT = "/tmp/translation-checker" if os.path.isdir("/tmp") else "runs"
os.makedirs(UPLOAD_ROOT, exist_ok=True)
ALLOWED = {".txt", ".docx"}

def _ext_ok(name): 
    return os.path.splitext(name or "")[1].lower() in ALLOWED

@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "File too large (max 20MB)."}), 413

@app.get("/")
def index():
    return render_template("index.html")

@app.post("/analyze")
def analyze():
    try:
        if "original" not in request.files or "translation" not in request.files:
            return jsonify({"error": "Upload both files (original & translation)."}), 400

        mode = request.form.get("mode", "python")  # 'python' or 'chatgpt'
        orig = request.files["original"]
        tran = request.files["translation"]

        if not orig.filename or not tran.filename:
            return jsonify({"error": "Choose both files before submitting."}), 400
        if not _ext_ok(orig.filename) or not _ext_ok(tran.filename):
            return jsonify({"error": "Only .txt and .docx are supported."}), 400

        run_id = str(uuid.uuid4())
        run_dir = os.path.join(UPLOAD_ROOT, run_id)
        os.makedirs(run_dir, exist_ok=True)
        op = os.path.join(run_dir, secure_filename(orig.filename))
        tp = os.path.join(run_dir, secure_filename(tran.filename))
        orig.save(op)
        tran.save(tp)

        src_txt = to_text(op)
        tgt_txt = to_text(tp)
        if not src_txt.strip() or not tgt_txt.strip():
            return jsonify({"error": "Could not read text from one of the files."}), 400

        src_segments, tgt_segments = simple_align(src_txt, tgt_txt)

        if mode == "chatgpt":
            key_path = os.path.join(os.path.dirname(__file__), "local_openai_key.txt")
            if not os.path.exists(key_path):
                return jsonify({"error": "ChatGPT mode selected but local_openai_key.txt not found."}), 400
            with open(key_path, "r", encoding="utf-8") as f:
                api_key = f.read().strip()
            results = run_checks_llm(src_segments, tgt_segments, api_key)
        else:
            results = run_checks_python(src_segments, tgt_segments)

        with open(os.path.join(run_dir, "results.json"), "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        return jsonify({
            "run_id": run_id,
            "summary": results.get("summary", {}),
            "issues": results.get("issues", [])
        })

    except Exception as e:
        # Show the actual error string (helps diagnose ChatGPT mode failures)
        return jsonify({"error": f"Analyze failed: {type(e).__name__}: {str(e)}"}), 500

@app.get("/report/<run_id>")
def report(run_id):
    fp = os.path.join(UPLOAD_ROOT, run_id, "results.json")
    if not os.path.exists(fp):
        return "Report not found", 404
    with open(fp, encoding="utf-8") as f:
        data = json.load(f)
    return render_template("report.html", data=data, run_id=run_id)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
