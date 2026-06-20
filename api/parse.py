import os
import sys
import zipfile
import tempfile
import traceback

from flask import Flask, request, jsonify, send_file

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)
import tool

app = Flask(__name__)


@app.route("/")
def index():
    return send_file(os.path.join(ROOT_DIR, "index.html"))


@app.route("/api/parse", methods=["POST"])
def parse():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded. Expected form field 'file'."}), 400

    uploaded = request.files["file"]
    filename = uploaded.filename or "upload.yyz"

    try:
        with tempfile.TemporaryDirectory(prefix="gms2_") as tmp_dir:
            archive_path = os.path.join(tmp_dir, filename)
            uploaded.save(archive_path)

            if not zipfile.is_zipfile(archive_path):
                return jsonify({"error": f"'{filename}' is not a valid .yyz/zip archive."}), 400

            extract_dir = os.path.join(tmp_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(extract_dir)

            entries = os.listdir(extract_dir)
            yyp_at_root = any(e.endswith(".yyp") for e in entries)
            if not yyp_at_root and len(entries) == 1 and os.path.isdir(os.path.join(extract_dir, entries[0])):
                project_root = os.path.join(extract_dir, entries[0])
            else:
                project_root = extract_dir

            result = tool.process_project(project_root)
    except Exception:
        return jsonify({"error": traceback.format_exc()}), 500

    return jsonify(result)
