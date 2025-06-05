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
  <img id="map" src="{{'route_overlay.png' if raw else 'trinity_map_original.png'}}">
  <div id="gps-dot" style="display:none;"></div>
  <div id="gps-error-circle" style="display:none;"></div>
</div>

<script>
let zoomLevel = 1.0;
let offsetX = 0, offsetY = 0;
const map = document.getElementById('map');
const wrapper = document.getElementById('map-wrapper');

function setZoom(level) {
  zoomLevel = Math.max(0.2, Math.min(4.0, level));
  map.style.transform = `scale(${zoomLevel})`;
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
  updateOverlayPosition();
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

      dot.style.display = 'block';
      ring.style.display = 'block';

      updateOverlayPosition();
    }
  }, 1000);
}
</script>


</body>
</html>
"""
