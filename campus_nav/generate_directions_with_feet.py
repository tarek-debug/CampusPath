#!/usr/bin/env python3
import pickle
import json
import numpy as np
import networkx as nx
from scipy.spatial import KDTree
import math
import cv2
import sys

# ─── CONFIG ──────────────────────────────────────────────────────────────
GRAPH_PKL        = "trinity_path_graph.gpickle"
BUILDING_MAP     = "building_to_node_mapping.json"
BUILDING_COORDS  = "building_coordinates_all.json"
INPUT_MAP        = "trinity_map_original.png"

# default start/end if no CLI args
START            = "Ogilby Hall"
END              = "Crescent Street Townhouses"

NODE_LIST_OUT    = "path_nodes.txt"
INSTR_PIX_OUT    = "instructions_pixels.txt"
INSTR_FEET_OUT   = "instructions_feet.txt"
OVERLAY_OUT      = "route_overlay.png"
LANDMARK_RADIUS  = 200   # px

# ** Calibration segments: ((x1,y1),(x2,y2), feet) **
CALIBRATION = [
    ((479,  849), (2705,  705), 1617),  # top horizontal
    ((2706, 199), (2685, 5003), 3448),  # right vertical
    ((1854,1237), (1886, 1757),  358),  # stadium length
    ((1668,2570), (1701, 2906),  240),  # tennis courts
]
# ─────────────────────────────────────────────────────────────────────────

def calibrate_factor():
    factors = []
    for (x1,y1),(x2,y2),feet in CALIBRATION:
        pix = math.hypot(x2-x1, y2-y1)
        factors.append(feet / pix)
    return sum(factors)/len(factors)

def load_data():
    G      = pickle.load(open(GRAPH_PKL, "rb"))
    b2n    = json.load(open(BUILDING_MAP))
    bcoords= json.load(open(BUILDING_COORDS))
    return G, b2n, bcoords

def find_route(G, b2n, start, end):
    nodes = [tuple(map(int, n)) for n in G.nodes()]
    tree  = KDTree(nodes)
    sx,sy = b2n[start]; ex,ey = b2n[end]
    _, si = tree.query((sx, sy))
    _, ei = tree.query((ex, ey))
    src, dst = nodes[si], nodes[ei]
    if not nx.has_path(G, src, dst):
        raise RuntimeError(f"No route between {start!r} and {end!r}")
    return nx.shortest_path(G, src, dst, weight="weight")

def save_node_list(path):
    with open(NODE_LIST_OUT, "w") as f:
        for x,y in path:
            f.write(f"{x},{y}\n")

def extract_landmarks(path, bcoords):
    names = list(bcoords.keys())
    pts   = np.array([bcoords[n] for n in names])
    tree  = KDTree(pts)
    seen  = {}
    for i,(x,y) in enumerate(path):
        dist, idx = tree.query((x,y))
        if dist <= LANDMARK_RADIUS:
            nm = names[idx]
            if nm not in seen:
                seen[nm] = i
    return sorted(seen.items(), key=lambda kv: kv[1])

def direction(dx, dy):
    if abs(dx)>abs(dy):
        return "east" if dx>0 else "west"
    else:
        return "south" if dy>0 else "north"

def make_instructions(landmarks, bcoords, factor):
    pix_lines = []; ft_lines = []
    if not landmarks:
        return ["No landmarks found."], ["No landmarks found."]
    first,_ = landmarks[0]
    pix_lines.append(f"Start at {first}.")
    ft_lines.append(f"Start at {first}.")
    for (curr,i),(nxt,j) in zip(landmarks, landmarks[1:]):
        x1,y1 = bcoords[curr]; x2,y2 = bcoords[nxt]
        dx,dy = x2-x1, y2-y1
        dpix = math.hypot(dx,dy)
        dft  = dpix * factor
        dir_ = direction(dx,dy)
        pix_lines.append(f"Then go {dir_} about {dpix:.1f} pixels to {nxt}.")
        ft_lines.append(f"Then go {dir_} about {dft:.0f} feet to {nxt}.")
    last,_ = landmarks[-1]
    pix_lines.append(f"Arrive at {last}.")
    ft_lines.append(f"Arrive at {last}.")
    return pix_lines, ft_lines

def draw_overlay(path, landmarks, bcoords):
    img = cv2.imread(INPUT_MAP)
    for a,b in zip(path, path[1:]):
        cv2.line(img, tuple(a), tuple(b), (0,0,255), 2)
    for nm,_ in landmarks:
        x,y = map(int, bcoords[nm])
        cv2.circle(img,(x,y),10,(0,255,0),-1)
        cv2.putText(img,nm,(x+5,y-5),
                    cv2.FONT_HERSHEY_SIMPLEX,0.4,(255,255,255),1)
    cv2.imwrite(OVERLAY_OUT, img)

def compute_route(start, end):
    G, b2n, bcoords = load_data()
    factor = calibrate_factor()
    path = find_route(G, b2n, start, end)
    landmarks = extract_landmarks(path, bcoords)
    pix_lines, ft_lines = make_instructions(landmarks, bcoords, factor)
    return pix_lines, ft_lines, path, landmarks

if __name__ == "__main__":
    # if two args: just print the feet instructions
    if len(sys.argv) == 3:
        s,e = sys.argv[1], sys.argv[2]
        _, feet, _, _ = compute_route(s, e)
        for line in feet:
            print(line)
        sys.exit(0)

    # else: use default START/END, write files & draw overlay
    factor = calibrate_factor()
    print(f"Calibrated: {factor:.3f} feet/pixel")
    pix_lines, ft_lines, path, landmarks = compute_route(START, END)

    save_node_list(path)
    with open(INSTR_PIX_OUT,"w") as f: f.write("\n".join(pix_lines))
    with open(INSTR_FEET_OUT,"w") as f: f.write("\n".join(ft_lines))
    draw_overlay(path, landmarks, json.load(open(BUILDING_COORDS)))
    print("\n".join(ft_lines))
