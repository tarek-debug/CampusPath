#!/usr/bin/env python3
import pickle, json, numpy as np, networkx as nx, math, cv2, sys
from scipy.spatial import KDTree

# ─── CONFIG ──────────────────────────────────────────────────────────────
GRAPH_PKL        = "trinity_path_graph.gpickle"
BUILDING_MAP     = "building_to_node_mapping.json"
BUILDING_COORDS  = "building_coordinates_all.json"
INPUT_MAP        = "trinity_map_original.png"

NODE_LIST_OUT    = "path_nodes.txt"
INSTR_PIX_OUT    = "instructions_pixels.txt"
INSTR_FEET_OUT   = "instructions_feet.txt"
OVERLAY_OUT      = "route_overlay.png"
LANDMARK_RADIUS  = 200  # px

CALIBRATION = [
    ((479,  849), (2705,  705), 1617),
    ((2706, 199), (2685, 5003), 3448),
    ((1854,1237), (1886, 1757),  358),
    ((1668,2570), (1701, 2906),  240),
]
# ─────────────────────────────────────────────────────────────────────────

def calibrate_factor():
    return sum(feet / math.hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2), feet in CALIBRATION) / len(CALIBRATION)

def load_data():
    G       = pickle.load(open(GRAPH_PKL, "rb"))
    b2n     = json.load(open(BUILDING_MAP))
    bcoords = json.load(open(BUILDING_COORDS))
    return G, b2n, bcoords

def find_route(G, b2n, start, end):
    nodes = [tuple(map(int, n)) for n in G.nodes()]
    tree  = KDTree(nodes)
    if start not in b2n or end not in b2n:
        raise ValueError(f"Start or end building not found: {start}, {end}")
    sx, sy = b2n[start]; ex, ey = b2n[end]
    _, si = tree.query((sx, sy))
    _, ei = tree.query((ex, ey))
    src, dst = nodes[si], nodes[ei]
    if not nx.has_path(G, src, dst):
        raise RuntimeError(f"No path found between '{start}' and '{end}'")
    return nx.shortest_path(G, src, dst, weight="weight")

def save_node_list(path):
    with open(NODE_LIST_OUT, "w") as f:
        for x, y in path:
            f.write(f"{x},{y}\n")

def extract_landmarks(path, bcoords):
    names = list(bcoords.keys())
    pts   = np.array([bcoords[n] for n in names])
    tree  = KDTree(pts)
    seen  = {}
    for i, (x, y) in enumerate(path):
        dist, idx = tree.query((x, y))
        if dist <= LANDMARK_RADIUS:
            nm = names[idx]
            if nm not in seen:
                seen[nm] = i
    return sorted(seen.items(), key=lambda kv: kv[1])

def direction(dx, dy):
    return "east" if abs(dx) > abs(dy) and dx > 0 else \
           "west" if abs(dx) > abs(dy) else \
           "south" if dy > 0 else "north"

def make_instructions(landmarks, bcoords, factor):
    pix_lines, ft_lines = [], []
    if not landmarks:
        return ["No landmarks found."], ["No landmarks found."]
    first, _ = landmarks[0]
    pix_lines.append(f"Start at {first}.")
    ft_lines.append(f"Start at {first}.")
    for (curr, _), (nxt, _) in zip(landmarks, landmarks[1:]):
        x1, y1 = bcoords[curr]
        x2, y2 = bcoords[nxt]
        dx, dy = x2 - x1, y2 - y1
        d_pix = math.hypot(dx, dy)
        d_ft = d_pix * factor
        dir_ = direction(dx, dy)
        pix_lines.append(f"Then go {dir_} about {d_pix:.1f} pixels to {nxt}.")
        ft_lines.append(f"Then go {dir_} about {d_ft:.0f} feet to {nxt}.")
    last, _ = landmarks[-1]
    pix_lines.append(f"Arrive at {last}.")
    ft_lines.append(f"Arrive at {last}.")
    return pix_lines, ft_lines

def _dotted_line(img, a, b, color=(255, 0, 0), spacing=15):
    """Draw a dotted line between ``a`` and ``b``."""
    dist = int(math.hypot(b[0] - a[0], b[1] - a[1]))
    for i in range(0, dist + 1, spacing):
        t = i / dist if dist else 0
        x = int(a[0] + (b[0] - a[0]) * t)
        y = int(a[1] + (b[1] - a[1]) * t)
        cv2.circle(img, (x, y), 3, color, -1)


def draw_overlay(path, landmarks, bcoords):
    img = cv2.imread(INPUT_MAP)
    for a, b in zip(path, path[1:]):
        _dotted_line(img, a, b)
    for nm, _ in landmarks:
        x, y = map(int, bcoords[nm])
        cv2.circle(img, (x, y), 10, (0, 255, 0), -1)
        cv2.putText(img, nm, (x + 5, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    cv2.imwrite(OVERLAY_OUT, img)

def compute_route(start, end):
    if not start or not end:
        raise ValueError("Start or end building not specified.")
    G, b2n, bcoords = load_data()
    factor = calibrate_factor()
    path = find_route(G, b2n, start, end)
    landmarks = extract_landmarks(path, bcoords)
    pix_lines, ft_lines = make_instructions(landmarks, bcoords, factor)
    return pix_lines, ft_lines, path, landmarks

# ─── CLI Mode ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 generate_directions_with_feet.py 'Start Building' 'End Building'")
        sys.exit(1)

    try:
        s, e = sys.argv[1], sys.argv[2]
        pix_lines, ft_lines, path, landmarks = compute_route(s, e)
        print(f"Directions from '{s}' to '{e}':\n")
        print("\n".join(ft_lines))
        save_node_list(path)
        with open(INSTR_PIX_OUT, "w") as f: f.write("\n".join(pix_lines))
        with open(INSTR_FEET_OUT, "w") as f: f.write("\n".join(ft_lines))
        draw_overlay(path, landmarks, json.load(open(BUILDING_COORDS)))
    except Exception as ex:
        print(f"[❌] Error: {ex}")
        sys.exit(1)
