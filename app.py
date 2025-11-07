# app.py
from flask import Flask, render_template, request, jsonify
import os, uuid, json
from services.extract import to_text
from services.align import simple_align
from services.checks import run_checks

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "runs"
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

@app.get("/")
def index():
    return render_template("index.html")

@app.post("/analyze")
def analyze():
    run_id = str(uuid.uuid4())
    run_dir = os.path.join(app.config["UPLOAD_FOLDER"], run_id)
    os.makedirs(run_dir, exist_ok=True)

    if "original" not in request.files or "translation" not in request.files:
        return jsonify({"error": "Please upload both files (original & translation)."}), 400

    orig = request.files["original"]
    tran = request.files["translation"]
    glossary = request.files.get("glossary")

    orig_path = os.path.join(run_dir, "original")
    tran_path = os.path.join(run_dir, "translation")
    orig.save(orig_path)
    tran.save(tran_path)
    glossary_path = None
    if glossary and glossary.filename:
        glossary_path = os.path.join(run_dir, "glossary.csv")
        glossary.save(glossary_path)

    src_txt = to_text(orig_path)
    tgt_txt = to_text(tran_path)

    src_segments, tgt_segments = simple_align(src_txt, tgt_txt)
    results = run_checks(src_segments, tgt_segments, glossary_path)

    with open(os.path.join(run_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return jsonify({
        "run_id": run_id,
        "summary": results.get("summary", {}),
        "issues": results.get("issues", [])
    })

@app.get("/report/<run_id>")
def report(run_id):
    fp = os.path.join(app.config["UPLOAD_FOLDER"], run_id, "results.json")
    if not os.path.exists(fp):
        return "Report not found", 404
    with open(fp, encoding="utf-8") as f:
        data = json.load(f)
    return render_template("report.html", data=data, run_id=run_id)

if __name__ == "__main__":
    app.run(debug=True)
