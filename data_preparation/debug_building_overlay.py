import json
import cv2

# Load image
img = cv2.imread("interactive_mask.png")

# Load building coords
with open("building_coordinates_test.json") as f:
    buildings = json.load(f)

# Draw circles for each building
for name, (x, y) in buildings.items():
    x, y = int(x), int(y)
    cv2.circle(img, (x, y), 10, (0, 255, 0), -1)
    cv2.putText(img, name, (x + 5, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

cv2.imwrite("building_overlay_debug.png", img)
print("Saved building_overlay_debug.png")
