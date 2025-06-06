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
      background: #f0f8ff;
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
      background: #ffffff;
      border: 1px solid #ddd;
      padding: 1rem;
      margin-bottom: 1rem;
      border-radius: 5px;
      overflow-x: auto;
      box-shadow: 0 2px 4px rgba(0,0,0,0.1);
      max-width: 100%;
    }
    .error {
      color: blue;
      font-weight: bold;
    }
    pre {
      white-space: pre-wrap;
      word-wrap: break-word;
    }

    #map-wrapper {
      position: relative;
      width: 100%;
      height: 600px;
      overflow: hidden;
      border: 1px solid #ccc;
      display: block;
      cursor: grab;
    }
    #map {
      position: absolute;
      top: 0;
      left: 0;
      transform-origin: top left;
      transition: transform 0.1s ease;
    }
    #route-canvas {
      position: absolute;
      top: 0;
      left: 0;
      pointer-events: none;
      z-index: 5;
    }
    #center-btn {
      position: absolute;
      bottom: 10px;
      right: 10px;
      z-index: 11;
    }
    #start-btn {
      position: absolute;
      bottom: 10px;
      left: 10px;
      z-index: 11;
    }
    #gps-dot {
      position: absolute;
      width: 10px;
      height: 10px;
      background: blue;
      border-radius: 50%;
      transform: translate(-50%, -50%);
      z-index: 10;
    }
    #gps-error-circle {
      position: absolute;
      width: 300px;
      height: 300px;
      background: rgba(0, 0, 255 , 0.2);
      border: 1px solid rgba(0, 0, 255, 0.4);
      border-radius: 80%;
      transform: translate(-50%, -50%);
      z-index: 9;
    }
  </style>
</head>
<body>

<h1>Campus Navigator</h1>
<form method="post">
  From:
  <input id="start" type="text" name="start" list="building-list" value="{{request.form.start or ''}}">
  <label><input type="checkbox" name="use_current" id="use_current"> Use my location</label>
  <br>
  To:
  <input id="end" type="text" name="end" list="building-list" value="{{request.form.end or ''}}" required>
  <input type="submit" value="Go">
</form>
<datalist id="building-list">
{% for b in buildings %}
  <option value="{{b}}">
{% endfor %}
</datalist>
{% if used_gps_start %}
  <div class="box">Starting near: {{used_gps_start}}</div>
{% endif %}

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
  <img id="map" src="trinity_map_original.png">
  <canvas id="route-canvas"></canvas>
  <div id="gps-dot" style="display:none;"></div>
  <div id="gps-error-circle" style="display:none;"></div>
  <button id="center-btn" type="button">⌖</button>
  <button id="start-btn" type="button" style="display:none;">Start</button>
</div>

<script>
let zoomLevel = 1.0;
let offsetX = 0, offsetY = 0;
const map = document.getElementById('map');
const wrapper = document.getElementById('map-wrapper');
const startInput = document.getElementById('start');
const useCurrent = document.getElementById('use_current');
const canvas = document.getElementById('route-canvas');
const ctx = canvas.getContext('2d');
const centerBtn = document.getElementById('center-btn');
const startBtn = document.getElementById('start-btn');
const pathData = {{ path_json|safe if path_json else 'null' }};
const showStart = {{ 'true' if show_start else 'false' }};
let walkedIndex = 0;
let started = false;
let currentX = null;
let currentY = null;

if (showStart && startBtn) startBtn.style.display = 'block';

useCurrent.addEventListener('change', () => {
  startInput.disabled = useCurrent.checked;
});

if (startBtn) {
  startBtn.addEventListener('click', () => {
    started = true;
  });
}

if (centerBtn) {
  centerBtn.addEventListener('click', () => {
    if (currentX == null || currentY == null) return;
    offsetX = wrapper.clientWidth / 2 - currentX * zoomLevel;
    offsetY = wrapper.clientHeight / 2 - currentY * zoomLevel;
    updateMapPosition();
  });
}

function setZoom(level) {
  zoomLevel = Math.max(0.2, Math.min(4.0, level));
  map.style.transform = `scale(${zoomLevel})`;
  canvas.style.transform = `scale(${zoomLevel})`;
  drawPath();
  updateOverlayPosition(); // ensure GPS stays accurate
}

document.addEventListener("keydown", (e) => {
  if (e.key === "+" || e.key === "=") setZoom(zoomLevel + 0.1);
  else if (e.key === "-") setZoom(zoomLevel - 0.1);
});

let isDragging = false, originX = 0, originY = 0;

wrapper.addEventListener('mousedown', (e) => {
  isDragging = true;
  originX = e.clientX - offsetX;
  originY = e.clientY - offsetY;
  wrapper.style.cursor = 'grabbing';
  e.preventDefault();
});

wrapper.addEventListener('touchstart', (e) => {
  if (e.touches.length === 1) {
    isDragging = true;
    originX = e.touches[0].clientX - offsetX;
    originY = e.touches[0].clientY - offsetY;
  }
});

document.addEventListener('mouseup', () => {
  isDragging = false;
  wrapper.style.cursor = 'grab';
});

document.addEventListener('touchend', () => {
  isDragging = false;
});

document.addEventListener('mousemove', (e) => {
  if (!isDragging) return;
  offsetX = e.clientX - originX;
  offsetY = e.clientY - originY;
  updateMapPosition();
});

document.addEventListener('touchmove', (e) => {
  if (!isDragging || e.touches.length !== 1) return;
  offsetX = e.touches[0].clientX - originX;
  offsetY = e.touches[0].clientY - originY;
  updateMapPosition();
  e.preventDefault();
}, { passive: false });

function updateMapPosition() {
  map.style.left = offsetX + 'px';
  map.style.top  = offsetY + 'px';
  canvas.style.left = offsetX + 'px';
  canvas.style.top  = offsetY + 'px';
  updateOverlayPosition();
  drawPath();
}

// Reposition dot + error circle on every map move
function updateOverlayPosition() {
  const dot = document.getElementById('gps-dot');
  const ring = document.getElementById('gps-error-circle');
  if (dot.dataset.x && dot.dataset.y) {
    const px = dot.dataset.x * zoomLevel + offsetX;
    const py = dot.dataset.y * zoomLevel + offsetY;
    dot.style.left = px + 'px';
    dot.style.top  = py + 'px';
    ring.style.left = px + 'px';
    ring.style.top  = py + 'px';
    ring.style.width = (250 * zoomLevel) + 'px';
    ring.style.height = (250 * zoomLevel) + 'px';
  }
}

function resizeCanvas() {
  canvas.width = map.naturalWidth;
  canvas.height = map.naturalHeight;
  drawPath();
}

function drawPath() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!pathData) return;
  ctx.setLineDash([10, 10]);
  ctx.lineWidth = 4;
  for (let i = 0; i < pathData.length - 1; i++) {
    ctx.strokeStyle = i < walkedIndex ? '#888' : 'blue';
    ctx.beginPath();
    ctx.moveTo(pathData[i][0], pathData[i][1]);
    ctx.lineTo(pathData[i + 1][0], pathData[i + 1][1]);
    ctx.stroke();
  }
}

function updateProgress(x, y) {
  if (!started || !pathData) return;
  let best = Infinity;
  let idx = walkedIndex;
  for (let i = walkedIndex; i < pathData.length; i++) {
    const dx = pathData[i][0] - x;
    const dy = pathData[i][1] - y;
    const d = Math.hypot(dx, dy);
    if (d < best) {
      best = d;
      idx = i;
    }
  }
  if (best < 20) walkedIndex = idx;
  if (walkedIndex >= pathData.length - 1 && best < 20) {
    alert('You have arrived!');
    started = false;
  }
  drawPath();
}

map.addEventListener('load', resizeCanvas);
if (map.complete) resizeCanvas();

// GPS tracking
if (navigator.geolocation) {
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
      const dot = document.getElementById('gps-dot');
      const ring = document.getElementById('gps-error-circle');

      dot.dataset.x = j.x;
      dot.dataset.y = j.y;

      currentX = j.x;
      currentY = j.y;

      dot.style.display = 'block';
      ring.style.display = 'block';

      updateOverlayPosition();
      updateProgress(j.x, j.y);
    }
  }, 1000);
}
</script>


</body>
</html>
"""
