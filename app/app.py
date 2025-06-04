#!/usr/bin/env python3
import sys, json, subprocess, shutil, os
from flask import Flask, request, render_template_string, send_from_directory

# try rapidfuzz, else fuzzywuzzy
try:
    from rapidfuzz import process
except ImportError:
    from fuzzywuzzy import process

from generate_directions_with_feet import compute_route, draw_overlay

app = Flask(__name__)

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
        safe_prompt = prompt.replace('"', '`"')
        script = f'echo "{safe_prompt}" | ollama run {OLLAMA_IMAGE}'
        cmd = [OLLAMA_EXE, "-Command", script]

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

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
