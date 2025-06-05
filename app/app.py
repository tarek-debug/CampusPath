#!/usr/bin/env python3
import os
import sys
import json
import pickle
import subprocess
import shutil
import numpy as np

from flask import (
    Flask,
    request,
    render_template_string,
    send_from_directory,
    jsonify,
    session
)
from datetime import timedelta

# ─── “Where is our piecewise‐affine mapper?” ─────────────────────────────────
# We assume:
#   - app.py lives in: /app/app.py
#   - gps_to_pixel folder lives in: /app/gps_to_pixel/
#
# So we add gps_to_pixel/ to sys.path, then import the mapper class.
GPS2PIXEL_FOLDER = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "gps_to_pixel")
)
if GPS2PIXEL_FOLDER not in sys.path:
    sys.path.append(GPS2PIXEL_FOLDER)

try:
    from piecewise_affine_inverse import PiecewiseAffineMapper
except ImportError:
    raise RuntimeError(
        f"Could not import piecewise_affine_inverse.py from {GPS2PIXEL_FOLDER!r}."
        " Please make sure mapper.pkl and piecewise_affine_inverse.py are both in that folder."
    )

# Load the pickled mapper at startup
MAPPER_PKL = os.path.join(GPS2PIXEL_FOLDER, "mapper.pkl")
if not os.path.exists(MAPPER_PKL):
    raise FileNotFoundError(
        f"mapper.pkl not found at {MAPPER_PKL!r}. Please generate it first."
    )
mapper = PiecewiseAffineMapper.load(MAPPER_PKL)
# ───────────────────────────────────────────────────────────────────────────────


app = Flask(__name__)
app.secret_key = "gps_tracking_session_key"
app.permanent_session_lifetime = timedelta(hours=1)

# ─── Load building list ────────────────────────────────────────────────────
b2n = json.load(open(os.path.join(os.path.dirname(__file__), "building_to_node_mapping.json")))
BUILDINGS = list(b2n.keys())
# ────────────────────────────────────────────────────────────────────────────


# ─── GPS → Pixel Conversion (piecewise‐affine + fallback) ─────────────────────
def gps_to_pixel(lat, lon):
    """
    1) Try exact inverse from piecewise‐affine mapper.
    2) If outside hull, fall back to nearest calibration anchor (in lat/lon space).
    """
    # 1) exact inverse
    xy = mapper.gps_to_pixel(lat, lon)
    if xy is not None:
        return int(round(xy[0])), int(round(xy[1]))

    # 2) fallback: nearest GPS anchor
    gps_array = mapper.gps_pts   # shape (N,2): [ [lat, lon], ... ]
    deltas = gps_array - np.array([lat, lon])
    d2 = np.sum(deltas * deltas, axis=1)
    idx = int(np.argmin(d2))

    pixel_array = mapper.pixel_pts  # shape (N,2): [ [x, y], ... ]
    x_anchor, y_anchor = pixel_array[idx]
    return int(round(x_anchor)), int(round(y_anchor))
# ────────────────────────────────────────────────────────────────────────────


# ─── Fuzzy Matching (rapidfuzz or fuzzywuzzy) ─────────────────────────────────
try:
    from rapidfuzz import process
except ImportError:
    from fuzzywuzzy import process

def fuzzy_building(name):
    match, score, _ = process.extractOne(name, BUILDINGS)
    return match if score >= 60 else None
# ────────────────────────────────────────────────────────────────────────────


# ─── Ollama Integration ─────────────────────────────────────────────────────
def find_ollama_executable():
    # 1) Check if “ollama” is already in WSL’s PATH
    if shutil.which("ollama"):
        print("[🧠] Found native WSL ollama.")
        return "ollama"

    # 2) Otherwise fall back to Windows PowerShell wrapper
    win_ps = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    if os.path.exists(win_ps):
        print(f"[🧠] Using PowerShell bridge at: {win_ps}")
        return win_ps

    print("[⚠️] No Ollama found in WSL or Windows.")
    return None

OLLAMA_EXE   = find_ollama_executable()
OLLAMA_IMAGE = "gemma3:1b"

def polish_with_ollama(feet_lines):
    if not OLLAMA_EXE:
        # No Ollama binary—skip
        return None

    prompt = (
        "You are a helpful and friendly assistant.\n"
        "Rewrite the following step-by-step walking directions into a cohesive, natural paragraph "
        "that sounds like something a real person would say. Use full sentences.\n\n"
        + "\n".join(feet_lines)
    )

    if OLLAMA_EXE == "ollama":
        # Native WSL
        cmd = [OLLAMA_EXE, "run", OLLAMA_IMAGE, "--stdin"]
        input_data = prompt.encode("utf-8")
    else:
        # Windows fallback via PowerShell
        # We need to escape quotes inside the prompt for PowerShell
        safe_prompt = prompt.replace("\\", "\\\\").replace('"', '`"')
        script = f"echo \"{safe_prompt}\" | ollama run {OLLAMA_IMAGE}"
        cmd = [OLLAMA_EXE, "-Command", script]
        input_data = None

    print(f"[🚀] Running: {' '.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            check=True,
            shell=False
        )
        print("[✅] Ollama polish complete.")
        return proc.stdout.decode("utf-8").strip()
    except subprocess.CalledProcessError as e:
        print(f"[🔥] Ollama failed (exit code {e.returncode})")
        print("[stderr]:", e.stderr.decode())
        return None
    except Exception as e:
        print("[❗] Unexpected error calling Ollama:", e)
        return None
# ────────────────────────────────────────────────────────────────────────────


# ─── HTML Template ─────────────────────────────────────────────────────────
# We assume you have moved your old triple‐quoted HTML into `html_template.py` as:
#
#   html_template.py:
#     HTML = """<!doctype html> <html> ... </html>"""
#
from html_template import HTML
# ────────────────────────────────────────────────────────────────────────────


# ─── Routes ───────────────────────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def index():
    error = raw = polished = None

    if request.method == "POST":
        a = request.form["start"].strip()
        b = request.form["end"].strip()
        s = fuzzy_building(a)
        e = fuzzy_building(b)

        if not s or not e:
            error = f"Could not match “{a}” or “{b}” to campus buildings."
        else:
            from generate_directions_with_feet import compute_route, draw_overlay

            pix, feet, path, landmarks = compute_route(s, e)
            raw = "\n".join(feet)

            # redraw route overlay onto original PNG
            draw_overlay(
                path,
                landmarks,
                json.load(open(os.path.join(os.path.dirname(__file__), "building_coordinates_all.json")))
            )

            # attempt to polish
            polished = polish_with_ollama(feet)

    return render_template_string(HTML, error=error, raw=raw, polished=polished, request=request)


@app.route("/route_overlay.png")
def overlay():
    # Serve the dynamically overwritten overlay
    return send_from_directory(".", "route_overlay.png")


@app.route("/trinity_map_original.png")
def original_map():
    return send_from_directory(".", "trinity_map_original.png")


@app.route("/update_location", methods=["POST"])
def update_location():
    data = request.get_json(force=True) or {}
    lat = data.get("lat")
    lon = data.get("lon")
    if lat is not None and lon is not None:
        session["gps"] = {"lat": lat, "lon": lon}
    print(f"📍 Received GPS coords: lat={lat}, lon={lon}")
    return "OK"


@app.route("/get_location")
def get_location():
    gps = session.get("gps")
    if not gps:
        return jsonify(x=None, y=None)

    x, y = gps_to_pixel(gps["lat"], gps["lon"])
    print(f"📍 Converting GPS ({gps['lat']}, {gps['lon']}) → Pixel ({x}, {y})")
    return jsonify(x=x, y=y)
# ────────────────────────────────────────────────────────────────────────────


# ─── Main ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Note: we bind to 0.0.0.0 so your phone on the same LAN can connect
    app.run(host="0.0.0.0", port=5000, debug=True)
