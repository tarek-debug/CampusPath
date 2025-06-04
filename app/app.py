#!/usr/bin/env python3
import os
import json
import subprocess
import shutil
from flask import Flask, request, render_template_string, send_from_directory, jsonify, session
from datetime import timedelta

# try rapidfuzz, else fuzzywuzzy
try:
    from rapidfuzz import process
except ImportError:
    from fuzzywuzzy import process

from generate_directions_with_feet import compute_route, draw_overlay

app = Flask(__name__)
app.secret_key = "gps_tracking_session_key"
app.permanent_session_lifetime = timedelta(hours=1)

# ─── Load building list ────────────────────────────────────────────────────
b2n = json.load(open("building_to_node_mapping.json"))
BUILDINGS = list(b2n.keys())

# ─── Calibration Points ────────────────────────────────────────────────────
CALIBRATION_FILE = "gps_calibration.json"
if os.path.exists(CALIBRATION_FILE):
    gps_to_pixel_data = json.load(open(CALIBRATION_FILE))
else:
    gps_to_pixel_data = {
        # latlon: (x,y)
        "41.747404,-72.690788": [479, 849],  # Vernon Street
        "41.746872,-72.687144": [2705, 705]  # Ice Hockey Center
    }

# ─── GPS to Pixel Conversion ───────────────────────────────────────────────
def gps_to_pixel(lat, lon):
    if not gps_to_pixel_data:
        return None, None
    # simple nearest-neighbor for now
    min_dist = float('inf')
    best_px = None
    for key, px in gps_to_pixel_data.items():
        plat, plon = map(float, key.split(","))
        dist = (plat - lat)**2 + (plon - lon)**2
        if dist < min_dist:
            min_dist = dist
            best_px = px
    return best_px if best_px else (None, None)

# ─── Fuzzy Matching ────────────────────────────────────────────────────────
def fuzzy_building(name):
    match, score, _ = process.extractOne(name, BUILDINGS)
    return match if score >= 60 else None

# ─── Ollama Integration ────────────────────────────────────────────────────
def find_ollama_executable():
    if shutil.which("ollama"):
        print("[🧠] Found native WSL ollama.")
        return "ollama"
    win_ps_path = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    if os.path.exists(win_ps_path):
        print(f"[🧠] Using PowerShell bridge at: {win_ps_path}")
        return win_ps_path
    print("[⚠️] No Ollama found in WSL or Windows.")
    return None

OLLAMA_EXE   = find_ollama_executable()
OLLAMA_IMAGE = "gemma3:1b"

def polish_with_ollama(feet_lines):
    if not OLLAMA_EXE:
        print("[❌] Skipping polish — no Ollama executable found.")
        return None

    prompt = (
        "You are a helpful and friendly assistant. Rewrite the following step-by-step walking directions "
        "into a coherent, natural paragraph that sounds like something a real person would say.\n\n"
        + "\n".join(feet_lines)
    )

    if OLLAMA_EXE == "ollama":
        cmd = [OLLAMA_EXE, "run", OLLAMA_IMAGE]
    else:
        script = f"echo \"{prompt.replace('\\', '\\\\').replace('"', '`"')}\" | ollama run {OLLAMA_IMAGE}"
        cmd = [OLLAMA_EXE, "/c", script]

    try:
        proc = subprocess.run(
            cmd,
            input=prompt.encode("utf-8") if OLLAMA_EXE == "ollama" else None,
            capture_output=True,
            check=True,
            shell=False
        )
        return proc.stdout.decode("utf-8").strip()

    except subprocess.CalledProcessError as e:
        print(f"[🔥] Ollama failed (code {e.returncode})")
        print("[stderr]:", e.stderr.decode())
        return None
    except Exception as e:
        print("[❗] Unexpected error calling Ollama:", str(e))
        return None

# ─── HTML Template ─────────────────────────────────────────────────────────
from html_template import HTML  # assuming you moved HTML block to html_template.py

# ─── Routes ────────────────────────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def index():
    error = raw = polished = None
    if request.method == "POST":
        a = request.form["start"].strip()
        b = request.form["end"].strip()
        s = fuzzy_building(a)
        e = fuzzy_building(b)
        if not s or not e:
            error = f"Could not match '{a}' or '{b}' to campus buildings."
        else:
            pix, feet, path, landmarks = compute_route(s, e)
            raw = "\n".join(feet)
            draw_overlay(path, landmarks, json.load(open("building_coordinates_all.json")))
            polished = polish_with_ollama(feet)
    return render_template_string(HTML, error=error, raw=raw, polished=polished, request=request)

@app.route('/route_overlay.png')
def overlay():
    return send_from_directory('.', 'route_overlay.png')

@app.route("/update_location", methods=["POST"])
def update_location():
    data = request.get_json()
    lat, lon = data.get("lat"), data.get("lon")
    if lat is not None and lon is not None:
        session['gps'] = {'lat': lat, 'lon': lon}
    return "OK"

@app.route("/get_location")
def get_location():
    gps = session.get('gps')
    if not gps:
        return jsonify(x=None, y=None)
    x, y = gps_to_pixel(gps['lat'], gps['lon'])
    return jsonify(x=x, y=y)

# ─── Main ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
