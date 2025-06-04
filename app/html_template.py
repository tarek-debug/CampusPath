HTML = """
<!doctype html>
<html>
<head>
  <title>Campus Navigator</title>
  <style>
    body {
      font-family: Arial, sans-serif;
      margin: 2rem auto;
      max-width: 1000px;
      padding: 0 1rem;
      overflow-x: hidden;
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
    #map-wrapper {
      position: relative;
      width: 100%;
      height: 600px;
      overflow: hidden;
      border: 1px solid #ccc;
      margin-bottom: 2rem;
      cursor: grab;
    }
    #map {
      position: absolute;
      top: 0;
      left: 0;
      transform-origin: top left;
      transition: transform 0.1s ease;
      max-width: none;
    }
    #gps-dot {
      position: absolute;
      width: 10px;
      height: 10px;
      background: red;
      border-radius: 50%;
      transform: translate(-50%, -50%);
      z-index: 10;
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
{% endif %}

<div class="box">
  <h2>Live Map View</h2>
  <div id="map-wrapper">
    <img id="map" src="{{ 'route_overlay.png' if raw else 'trinity_map_original.png' }}" />
    <div id="gps-dot"></div>
  </div>
  <p><small>Use + / - to zoom, drag to move. The red dot shows your real-time location.</small></p>
</div>

<script>
let zoomLevel = 1.0;
function setZoom(level) {
  zoomLevel = Math.max(0.2, Math.min(4.0, level));
  document.getElementById('map').style.transform = `scale(${zoomLevel})`;
}

// Zoom with keyboard
document.addEventListener("keydown", (e) => {
  if (e.key === "+" || e.key === "=") setZoom(zoomLevel + 0.1);
  else if (e.key === "-") setZoom(zoomLevel - 0.1);
});

// Drag map
let isDragging = false, originX = 0, originY = 0, offsetX = 0, offsetY = 0;
const map = document.getElementById('map');
const wrapper = document.getElementById('map-wrapper');

wrapper.addEventListener('mousedown', (e) => {
  isDragging = true;
  originX = e.clientX - offsetX;
  originY = e.clientY - offsetY;
  wrapper.style.cursor = 'grabbing';
});

document.addEventListener('mouseup', () => {
  isDragging = false;
  wrapper.style.cursor = 'grab';
});

document.addEventListener('mousemove', (e) => {
  if (!isDragging) return;
  offsetX = e.clientX - originX;
  offsetY = e.clientY - originY;
  map.style.left = offsetX + 'px';
  map.style.top  = offsetY + 'px';
});

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
    try {
      const r = await fetch('/get_location');
      const j = await r.json();
      if (j.x != null && j.y != null) {
        const dot = document.getElementById('gps-dot');
        dot.style.left = j.x * zoomLevel + offsetX + 'px';
        dot.style.top  = j.y * zoomLevel + offsetY + 'px';
        dot.style.display = 'block';
      }
    } catch (e) {
      console.error("GPS fetch failed", e);
    }
  }, 2000);
}
</script>

</body>
</html>
"""