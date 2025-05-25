import json
import pickle
from scipy.spatial import KDTree

# Load the graph
with open("trinity_path_graph.gpickle", "rb") as f:
    G = pickle.load(f)

# Load building coordinates
with open("building_coordinates_all.json") as f:
    building_coords = json.load(f)

# Prepare KD-Tree from node positions
positions = []
nodes = []
for node, data in G.nodes(data=True):
    # Ensure pos is a tuple of Python ints
    x, y = data.get('pos', node)
    xi, yi = int(x), int(y)
    positions.append((xi, yi))
    nodes.append((xi, yi))

tree = KDTree(positions)

# Snap each building to nearest graph node
building_to_node = {}
for name, coord in building_coords.items():
    dist, idx = tree.query(coord)
    building_to_node[name] = list(nodes[idx])  # list of ints, JSON-friendly

# Save mapping
with open("building_to_node_mapping.json", "w") as f:
    json.dump(building_to_node, f, indent=2)

print("Saved building-to-node mapping.")
