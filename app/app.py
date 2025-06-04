#!/usr/bin/env python3
import sys, json, subprocess, shutil, os
from flask import Flask, request, render_template_string, send_from_directory, jsonify
import numpy as np

# try rapidfuzz, else fuzzywuzzy
try:
    from rapidfuzz import process
except ImportError:
    from fuzzywuzzy import process

from generate_directions_with_feet import compute_route, draw_overlay

app = Flask(__name__)

# ─── Globals for GPS tracking ─────────────────────────────────────────────
current_latlon = None  # (lat, lon)
current_pixel  = None  # (x, y)

REF_POINTS = [
    ((41.12345, -72.54321), (1000, 800)),
    ((41.12390, -72.54250), (1400, 500)),
]
_A, _res, *_ = np.linalg.lstsq(
    np.array([[lon, lat, 1] for (lat, lon), _ in REF_POINTS]),
    np.array([[x, y] for _, (x, y) in REF_POINTS]),
    rcond=None
)

def gps_to_pixel(lat, lon):
    x, y = np.dot([lon, lat, 1], _A)
    return int(x), int(y)

# ─── Load building list ────────────────────────────────────────────────────
b2n = json.load(open("building_to_node_mapping.json"))
BUILDINGS = list(b2n.keys())
# ────────────────────────────────────────────────────────────────────────────

def fuzzy_building(name):
    match, score, _ = process.extractOne(name, BUILDINGS)
    return match if score >= 60 else None

def find_ollama_executable():
    # Prefer native WSL if available
    if shutil.which("ollama"):
        print("[🧠] Found native WSL ollama.")
        return "ollama"
    
    # Fallback to PowerShell bridge for Windows-based Ollama
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
        "You are a helpful and friendly assistant. "
        "Rewrite the following list of step-by-step walking directions into a coherent, natural paragraph "
        "that sounds like something a real person would say. Be clear, engaging, and avoid sounding too robotic. "
        "Combine short steps smoothly. Use full sentences.\n\n"
        + "\n".join(feet_lines)
    )

    if OLLAMA_EXE == "ollama":
        # Native WSL
        cmd = [OLLAMA_EXE, "run", OLLAMA_IMAGE]
    else:
        # Windows fallback via PowerShell
        script = f"echo \"{prompt.replace('\"', '`\"')}\" | ollama run {OLLAMA_IMAGE}"
        cmd = [OLLAMA_EXE, "/c", script]

    print(f"[🚀] Running: {' '.join(cmd)}")

    try:
        proc = subprocess.run(
            cmd,
            input=prompt.encode("utf-8") if OLLAMA_EXE == "ollama" else None,
            capture_output=True,
            check=True,
            shell=False
        )
        print("[✅] Ollama polishing complete.")
        return proc.stdout.decode("utf-8").strip()

    except subprocess.CalledProcessError as e:
        print(f"[🔥] Ollama failed (code {e.returncode})")
        print("[stderr]:", e.stderr.decode())
        return None

    except Exception as e:
        print("[❗] Unexpected error calling Ollama:", str(e))
        return None




HTML = """
<!doctype html>
<html>
<head>
  <title>Campus Navigator</title>
  <style>
    body {
      font-family: Arial, sans-serif;
      margin: 2rem auto;
      max-width: 800px;
      padding: 0 1rem;
    }
    h1 {
      color: #333;
    }
    form {
      margin-bottom: 1.5rem;
    }
    input[type="text"], input[type="submit"] {
      padding: 0.5rem;
      margin: 0.2rem;
      font-size: 1rem;
    }
    .box {
      background: #f9f9f9;
      border: 1px solid #ddd;
      padding: 1rem;
      margin-bottom: 1rem;
      border-radius: 5px;
      overflow-x: auto;
      max-width: 100%;
    }
    .error {
      color: red;
      font-weight: bold;
    }
    pre {
      white-space: pre-wrap;
      word-wrap: break-word;
    }
    #map-wrapper { position: relative; display: none; }
    #gps-dot {
      position: absolute;
      width: 10px;
      height: 10px;
      background: red;
      border-radius: 50%;
      transform: translate(-50%, -50%);
      display: none;
    }
  </style>
</head>
<body>

<h1>Campus Navigator</h1>
<form method=post>
  From: <input type="text" name="start" value="{{request.form.start or ''}}" required>
  To:   <input type="text" name="end"   value="{{request.form.end or ''}}" required>
  <input type="submit" value="Go">
</form>

{% if error %}
  <div class="box error">{{error}}</div>
{% endif %}

{% if raw %}
  <div class="box">
    <h2>Raw Directions</h2>
    <pre>{{raw}}</pre>
  </div>

  {% if polished %}
    <div class="box">
      <h2>Polished</h2>
      <pre>{{polished}}</pre>
    </div>
  {% else %}
    <div class="box">
      <em>Ollama not available; polish step skipped.</em>
    </div>
  {% endif %}

  <div class="box">
    <a href="/route_overlay.png" target="_blank">View Overlay Map 📍</a>
  </div>
{% endif %}
<div id="map-wrapper">
  <img id="map" src="/route_overlay.png">
  <div id="gps-dot"></div>
</div>

<script>
if (navigator.geolocation) {
    document.getElementById('map-wrapper').style.display = 'inline-block';
    navigator.geolocation.watchPosition(function(pos) {
        fetch('/update_location', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({lat: pos.coords.latitude, lon: pos.coords.longitude})
        });
    });
    setInterval(async () => {
        const r = await fetch('/get_location');
        const j = await r.json();
        if (j.x != null && j.y != null) {
            const img = document.getElementById('map');
            const dot = document.getElementById('gps-dot');
            const w = img.width, h = img.height;
            const x = Math.max(0, Math.min(w, j.x));
            const y = Math.max(0, Math.min(h, j.y));
            dot.style.left = x + 'px';
            dot.style.top  = y + 'px';
            dot.style.display = 'block';
        }
    }, 2000);
} else {
    document.getElementById('map-wrapper').style.display = 'none';
}
</script>

</body>
</html>
"""


@app.route("/", methods=["GET","POST"])
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

            # regenerate overlay
            draw_overlay(path, landmarks, json.load(open("building_coordinates_all.json")))

            # try polishing
            polished = polish_with_ollama(feet)

    return render_template_string(HTML, error=error, raw=raw, polished=polished, request=request)

@app.route('/route_overlay.png')
def overlay():
    return send_from_directory('.', 'route_overlay.png')

@app.route('/update_location', methods=['POST'])
def update_location():
    global current_latlon, current_pixel
    data = request.get_json(force=True) or {}
    lat = data.get('lat')
    lon = data.get('lon')
    if lat is None or lon is None:
        return jsonify({'status': 'error', 'msg': 'lat/lon required'}), 400
    current_latlon = (lat, lon)
    current_pixel = gps_to_pixel(lat, lon)
    return jsonify({'status': 'ok'})


@app.route('/get_location')
def get_location():
    if current_pixel is None:
        return jsonify({})
    x, y = current_pixel
    return jsonify({'x': int(x), 'y': int(y)})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
