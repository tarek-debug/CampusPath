#!/usr/bin/env python3
"""
interactive_path_tuner_web.py

1) Serve original map + in-browser pen/eraser.
2) Pen now draws opaque white; eraser punches holes.
3) On Submit, POST final mask → server, skeletonize, graph, save.
"""

import io, os, pickle
from flask import Flask, render_template_string, request, jsonify, send_from_directory
import cv2, numpy as np, networkx as nx
from skimage.morphology import skeletonize, remove_small_objects, remove_small_holes
from scipy.spatial import cKDTree
from PIL import Image

# ——— CONFIG ———
ORIG_PNG       = "trinity_map_original.png"
MASK_PNG       = "interactive_mask.png"
OVERLAY_PNG    = "skeleton_overlay.png"
GRAPH_PKL      = "trinity_path_graph.gpickle"

# post‐processing
MIN_PIXELS     = 150
FILL_HOLES     = 4000
CONNECT_RADIUS = 6
# —————————————————

app = Flask(__name__)

@app.route('/map.png')
def map_png():
    return send_from_directory('.', ORIG_PNG)

@app.route('/')
def index():
    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Interactive Path Tuner</title>
  <style>
    #container { position: relative; display: inline-block; }
    canvas { position: absolute; top: 0; left: 0; }
    #controls { margin: 1em; }
  </style>
</head>
<body>
  <div id="controls">
    <label>Pen size: <input id="pen" type="range" min="1" max="50" value="10"></label>
    <label>Eraser size: <input id="eraser" type="range" min="1" max="50" value="20"></label>
    <button id="submit">Submit</button>
    <span id="status"></span>
  </div>
  <div id="container">
    <canvas id="bg"></canvas>
    <canvas id="mask"></canvas>
  </div>
<script>
const bg = document.getElementById('bg'),
      mask = document.getElementById('mask'),
      penSlider = document.getElementById('pen'),
      eraserSlider = document.getElementById('eraser'),
      submitBtn = document.getElementById('submit'),
      status = document.getElementById('status');
let drawing=false, tool='pen';

let img = new Image();
img.onload = () => {
  [bg, mask].forEach(c => {
    c.width = img.width;
    c.height = img.height;
  });
  bg.getContext('2d').drawImage(img,0,0);
};
img.src = '/map.png';

mask.addEventListener('contextmenu', e=>e.preventDefault());
mask.addEventListener('mousedown', e=>{
  drawing = true;
  tool = (e.button===2 ? 'erase':'pen');
  draw(e);
});
mask.addEventListener('mouseup', ()=>drawing=false);
mask.addEventListener('mouseout', ()=>drawing=false);
mask.addEventListener('mousemove', e=>drawing && draw(e));

function draw(e){
  const rect = mask.getBoundingClientRect(),
        x = e.clientX - rect.left,
        y = e.clientY - rect.top,
        size = tool==='pen' ? +penSlider.value : +eraserSlider.value,
        ctx = mask.getContext('2d');

  if(tool==='pen'){
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = 'white';               // <-- opaque white
  } else {
    ctx.globalCompositeOperation = 'destination-out';
    // fillStyle doesn’t matter here
  }

  ctx.beginPath();
  ctx.arc(x,y,size,0,2*Math.PI);
  ctx.fill();
}

submitBtn.onclick = ()=>{
  status.textContent = 'Saving…';
  mask.toBlob(blob => {
    let data = new FormData();
    data.append('mask', blob, 'mask.png');
    fetch('/submit', {method:'POST', body:data})
      .then(r=>r.json())
      .then(j=>{
        status.textContent = j.success ? '✓ Done!' : '✗ '+j.error;
      })
      .catch(err=> status.textContent = '✗ '+err);
  }, 'image/png');
};
</script>
</body>
</html>
    """)

@app.route('/submit', methods=['POST'])
def submit():
    try:
        f = request.files['mask']
        img = Image.open(f.stream).convert('L')
        mask_arr = np.array(img)
        mask_bin = (mask_arr > 0).astype(np.uint8)

        # clean + skeletonize
        b = remove_small_holes(mask_bin.astype(bool), area_threshold=FILL_HOLES)
        b = remove_small_objects(b, min_size=MIN_PIXELS)
        sk = skeletonize(b).astype(np.uint8)

        # autobridge endpoints
        ys,xs = np.nonzero(sk)
        ends=[]
        offsets=[(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
        h,w = sk.shape
        for x,y in zip(xs,ys):
            nb = sum(1 for dx,dy in offsets
                     if 0<=x+dx<w and 0<=y+dy<h and sk[y+dy,x+dx])
            if nb==1:
                ends.append((x,y))
        if ends:
            tree=cKDTree(ends)
            for i,j in tree.query_pairs(CONNECT_RADIUS):
                x1,y1=ends[i]; x2,y2=ends[j]
                cv2.line(sk,(x1,y1),(x2,y2),1,1)

        # build graph
        G=nx.Graph()
        for x,y in zip(xs,ys):
            if sk[y,x]:
                G.add_node((x,y), x=int(x), y=int(y))
        for x,y in zip(xs,ys):
            for dx,dy in offsets:
                nx_,ny_ = x+dx, y+dy
                if 0<=nx_<w and 0<=ny_<h and sk[ny_,nx_]:
                    G.add_edge((x,y),(nx_,ny_), weight=float(np.hypot(dx,dy)))

        # save mask, overlay, graph
        cv2.imwrite(MASK_PNG, (mask_bin*255).astype(np.uint8))
        orig = cv2.imread(ORIG_PNG)
        over = orig.copy()
        ys2,xs2 = np.nonzero(sk)
        over[ys2,xs2] = (0,0,255)
        cv2.imwrite(OVERLAY_PNG, over)
        with open(GRAPH_PKL,'wb') as f: pickle.dump(G,f)

        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, error=str(e))

if __name__=='__main__':
    app.run(debug=True, port=5001, use_reloader=False)
