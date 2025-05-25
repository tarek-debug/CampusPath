import json
from flask import Flask, request, jsonify, send_from_directory, render_template_string

# ——— CONFIG ———
ORIG_PNG = "trinity_map_original.png"
SAVE_JSON = "corrected_building_coordinates.json"
# full building list
BUILDINGS = [
    "Cultural Programs in Italy",
    "Cornelia Center",
    "Boys & Girls Club at Trinity College",
    "Cinestudio",
    "Ferris Athletic Center",
    "Jessee/Miller Football Field and Track",
    "Koeppel Community Sports Center",
    "DiBenedetto Stadium",
    "Paul D. Assaiante Tennis Center",
    "Robin L. Sheppard Field",
    "Trinity Soccer Field",
    "Trinity Softball Diamond",
    "Koeppel Student Center/The Bistro",
    "Hartford Youth Scholars",
    "Albert C. Jacobs Life Sciences Center Quad",
    "Alpha Delta Phi",
    "Asian American Student Association",
    "Chapel",
    "Charleston House of Interfaith Cooperation",
    "Cleo Society of AX",
    "Gates Quad",
    "International House",
    "Pi Kappa Alpha",
    "Psi Upsilon",
    "Queer Resource Center",
    "The Mill",
    "Umoja House",
    "Zachs Hillel House",
    "Clemens Hall",
    "Cook Hall",
    "Crescent Street Townhouses",
    "Doonesbury Hall",
    "Elton Hall",
    "Funston Hall",
    "Goodwin-Woodward Hall",
    "Hansen Hall",
    "High Rise Hall",
    "Jackson Hall",
    "Jarvis Hall",
    "Jones Hall",
    "North Campus Hall",
    "Northam Towers",
    "Ogilby Hall",
    "Summit Suites North & South",
    "Summit Suites East",
]

# —————————————————

app = Flask(__name__)

@app.route('/map.png')
def map_png():
    return send_from_directory('.', ORIG_PNG)

@app.route('/')
def index():
    return render_template_string(r"""
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Building Coordinate Picker</title>
<style>
  #container { position: relative; display: inline-block; }
  canvas { position: absolute; top: 0; left: 0; }
  #controls { margin: 1em; }
  #hover-label { position: absolute; pointer-events: none; color: yellow; background: rgba(0,0,0,0.5); padding:2px 4px; border-radius:4px; font-family:sans-serif; font-size:12px; }
</style>
</head><body>
<div id="controls">
  <button id="undo" disabled>Undo</button>
  <button id="submit" disabled>Submit Coordinates</button>
  <span id="status"></span>
</div>
<div id="container">
  <canvas id="bg"></canvas>
  <canvas id="overlay"></canvas>
  <div id="hover-label"></div>
</div>
<script>
const buildings = {{ buildings|tojson }};
let idx = 0;
const coords = {};
const history = [];
const bg = document.getElementById('bg');
const overlay = document.getElementById('overlay');
const hoverLabel = document.getElementById('hover-label');
const undoBtn = document.getElementById('undo');
const submitBtn = document.getElementById('submit');
const status = document.getElementById('status');
let img = new Image();
img.onload = ()=>{
  [bg, overlay].forEach(c=>{ c.width = img.width; c.height = img.height; });
  bg.getContext('2d').drawImage(img,0,0);
  updateHoverLabelPosition(0,0);
};
img.src = '/map.png';

function updateHoverLabelPosition(x, y) {
  hoverLabel.style.left = (x + 10) + 'px';
  hoverLabel.style.top = (y + 10) + 'px';
  hoverLabel.textContent = idx < buildings.length ? buildings[idx] : '';
}

overlay.addEventListener('mousemove', e=>{
  const rect = overlay.getBoundingClientRect();
  updateHoverLabelPosition(e.clientX - rect.left, e.clientY - rect.top);
});

overlay.addEventListener('click', e=>{
  if(idx >= buildings.length) return;
  const rect = overlay.getBoundingClientRect();
  const x = Math.round(e.clientX - rect.left);
  const y = Math.round(e.clientY - rect.top);
  const name = buildings[idx];
  coords[name] = [x, y];
  history.push(name);
  redrawMarkers();
  idx++;
  undoBtn.disabled = history.length === 0;
  if(idx === buildings.length) submitBtn.disabled = false;
});

undoBtn.onclick = ()=>{
  if(history.length === 0) return;
  const last = history.pop();
  delete coords[last];
  idx = history.length;
  redrawMarkers();
  undoBtn.disabled = history.length === 0;
  submitBtn.disabled = true;
};

function redrawMarkers() {
  const ctx = overlay.getContext('2d');
  ctx.clearRect(0,0,overlay.width, overlay.height);
  let i = 0;
  for(const b of history) {
    const [x, y] = coords[b];
    ctx.fillStyle = 'rgba(0,255,0,0.7)';
    ctx.beginPath(); ctx.arc(x,y,5,0,2*Math.PI); ctx.fill();
    ctx.fillStyle = 'white'; ctx.font = '12px sans-serif';
    ctx.fillText(b, x+5, y-5);
    i++;
  }
}

submitBtn.onclick = ()=>{
  submitBtn.disabled = true;
  status.textContent = 'Saving...';
  fetch('/submit', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(coords)
  }).then(r=>r.json()).then(j=>{
    status.textContent = j.success ? '✅ Saved!' : '✗ '+j.error;
  }).catch(e=> status.textContent = '✗ '+e);
};
</script>
</body></html>
    """, buildings=BUILDINGS)

@app.route('/submit', methods=['POST'])
def submit():
    try:
        data = request.get_json()
        with open(SAVE_JSON, 'w') as f:
            json.dump(data, f, indent=2)
        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, error=str(e))

if __name__ == '__main__':
    app.run(debug=True, port=5002, use_reloader=False)
