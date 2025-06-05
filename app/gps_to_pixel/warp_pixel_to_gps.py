#!/usr/bin/env python3
"""
warp_pixel_to_gps.py

A script to perform piecewise-affine warping from pixel coordinates to GPS (latitude, longitude)
using Delaunay triangulation and per-triangle affine transforms.

Requirements:
    - Python 3.7+
    - numpy
    - scipy

Usage:
    Place your calibration JSON file (`gps_calibration.json`) in the same directory as this script.
    Run:
        python warp_pixel_to_gps.py

This will:
    1. Load calibration points from `gps_calibration.json`.
    2. Perform a Delaunay triangulation over the pixel coordinates.
    3. Compute a 2×2 affine matrix and translation vector for each triangle that maps
       (x, y) → (lat, lon).
    4. Define a function `pixel_to_gps(x, y)` that finds the containing triangle and applies
       the corresponding affine transform.
    5. (Optional) Build a KDTree for inverse lookups (lat, lon) → nearest calibration pixel.
"""

import json
import os
import numpy as np
from scipy.spatial import Delaunay, KDTree


def load_calibration(cal_file: str):
    """
    Load calibration points from a JSON file. Each entry must have:
        - 'x', 'y' (pixel coordinates)
        - 'lat', 'lon' (GPS coordinates)
    Returns:
        pixel_coords: (N, 2) numpy array of pixel (x, y)
        gps_coords:   (N, 2) numpy array of (lat, lon)
    """
    with open(cal_file, 'r') as f:
        data = json.load(f)

    pixel_list = []
    gps_list = []

    for entry in data:
        if all(k in entry for k in ("x", "y", "lat", "lon")):
            pixel_list.append([entry["x"], entry["y"]])
            gps_list.append([entry["lat"], entry["lon"]])
        else:
            raise ValueError(f"Missing keys in calibration entry: {entry}")

    pixel_coords = np.vstack(pixel_list)  # shape (N, 2)
    gps_coords = np.vstack(gps_list)      # shape (N, 2)

    return pixel_coords, gps_coords


def compute_triangle_affines(pixel_coords: np.ndarray, gps_coords: np.ndarray, delaunay: Delaunay):
    """
    For each triangle (simplex) in the Delaunay triangulation, compute the affine transform
    that maps pixel (x, y, 1) → (lat, lon).

    The transform for triangle i is:
        [lat; lon] = A_i @ [x; y] + b_i

    We solve for A_i (2×2) and b_i (2×1) exactly, given three corner correspondences.

    Returns:
        affines: list of dicts of length T (# of triangles). Each dict has:
            'vertices': indices of the 3 calibration points (into pixel_coords/gps_coords)
            'A': (2×2) numpy array
            'b': (2,) numpy array
    """
    affines = []

    for simplex in delaunay.simplices:
        # simplex is a length-3 array of indices into pixel_coords / gps_coords
        pts_pix = pixel_coords[simplex]   # shape (3, 2)
        pts_gps = gps_coords[simplex]     # shape (3, 2)

        # We want: [x_i, y_i, 1] @ [a11 a12; a21 a22; tx ty]^T = [lat_i, lon_i]
        # Or equivalently: [ [x1, y1, 1],
        #                    [x2, y2, 1],
        #                    [x3, y3, 1] ] @ M^T = [ [lat1, lon1],
        #                                            [lat2, lon2],
        #                                            [lat3, lon3] ]
        #
        # Let X = [[x1, y1, 1],
        #          [x2, y2, 1],
        #          [x3, y3, 1]]  (3×3)
        # Let Y = [[lat1, lon1],
        #          [lat2, lon2],
        #          [lat3, lon3]]  (3×2)
        #
        # Solve for M: (3×3) M^T = Y  →  M^T = X^-1 @ Y  → M = (Y^T @ (X^-T))
        #
        # Then M has shape (2, 3). We can decompose:
        #    A_i = M[:, :2]   (2×2)
        #    b_i = M[:, 2]    (2,)

        X = np.vstack([
            np.hstack([pts_pix[0], 1.0]),
            np.hstack([pts_pix[1], 1.0]),
            np.hstack([pts_pix[2], 1.0])
        ])  # (3, 3)

        Y = pts_gps  # (3, 2)

        # Solve M^T = X^{-1} @ Y  →  M = (X^{-T} @ Y.T).T
        try:
            X_inv = np.linalg.inv(X)       # (3, 3)
        except np.linalg.LinAlgError:
            # Degenerate triangle (collinear points), skip or handle
            raise RuntimeError(f"Degenerate triangle with points: {pts_pix}")

        M_full = (X_inv @ Y)            # (3, 2). But that's actually X_inv.T @ Y.T? Let's check:
        # Actually, (X @ M.T = Y) → M.T = X^{-1} @ Y → M = (Y.T @ X^{-T}).T.
        # But if we do M_full = X_inv @ Y, we get shape (3,2): each row i is coefficients mapping to lat/lon?
        # Let's verify by testing: X (3×3) times M_full (3×2) = (3×2) equals Y? Yes:
        #   X (3×3) @ (3×2) = (3×2) → equals Y. So M_full = 3×2. We can transpose to get M: (2×3).
        M = M_full.T   # shape (2, 3)

        # Decompose:
        A = M[:, :2]   # (2, 2)
        b = M[:, 2]    # (2,)

        affines.append({
            "vertices": simplex.copy(),
            "A": A,
            "b": b
        })

    return affines


def build_affine_lookup(pixel_coords: np.ndarray, gps_coords: np.ndarray):
    """
    Build the Delaunay triangulation, compute per-triangle affine maps, and return:
        - delaunay: the Delaunay object on pixel_coords
        - affines: list of dicts with keys 'vertices', 'A', 'b'
    """
    delaunay = Delaunay(pixel_coords)
    affines = compute_triangle_affines(pixel_coords, gps_coords, delaunay)
    return delaunay, affines


class PixelToGPSMapper:
    """
    Encapsulates the Delaunay-based piecewise-affine mapping from pixel → (lat, lon).
    """

    def __init__(self, pixel_coords: np.ndarray, gps_coords: np.ndarray):
        """
        Initialize by building triangulation and computing affines.
        """
        self.pixel_coords = pixel_coords
        self.gps_coords = gps_coords
        self.delaunay, self.affines = build_affine_lookup(pixel_coords, gps_coords)

    def pixel_to_gps(self, x: float, y: float):
        """
        Map a single pixel coordinate (x, y) → (lat, lon) by:
            1. Finding which triangle (simplex) contains (x, y).
            2. Applying that triangle's affine transform.

        Returns:
            (lat, lon) as a tuple of floats, or None if (x, y) is outside convex hull.
        """
        simplex_index = self.delaunay.find_simplex(np.array([[x, y]]))  # returns array([index]) or [-1]
        tri_idx = int(simplex_index[0])
        if tri_idx == -1:
            # outside all triangles
            return None

        # Retrieve affine params for this triangle
        affine = self.affines[tri_idx]
        A = affine["A"]   # shape (2, 2)
        b = affine["b"]   # shape (2,)

        # Compute [lat; lon] = A @ [x; y] + b
        px = np.array([x, y])       # (2,)
        latlon = A.dot(px) + b      # (2,)
        lat, lon = float(latlon[0]), float(latlon[1])
        return lat, lon

    def batch_pixel_to_gps(self, xy_array: np.ndarray):
        """
        Map a batch of pixel coordinates (N×2) → (N×2) latlon array. Points outside convex hull get (nan, nan).
        """
        N = xy_array.shape[0]
        result = np.full((N, 2), np.nan, dtype=float)

        simplex_indices = self.delaunay.find_simplex(xy_array)  # shape (N,)
        for i in range(N):
            tri_idx = int(simplex_indices[i])
            if tri_idx == -1:
                continue
            A = self.affines[tri_idx]["A"]
            b = self.affines[tri_idx]["b"]
            result[i] = A.dot(xy_array[i]) + b

        return result

    def build_inverse_kdtree(self):
        """
        (Optional) Build a KDTree on the calibration GPS points for nearest-neighbor reverse lookup:
            (lat, lon) → nearest pixel (among the original calibration points).
        This is only an approximate inverse; for a more accurate inverse you'd need to sample more points.

        Returns:
            KDTree built on self.gps_coords, and pixel_coords for reference.
        """
        self.inverse_kdtree = KDTree(self.gps_coords)    # KDTree on (lat, lon)
        return self.inverse_kdtree

    def approx_gps_to_pixel(self, lat: float, lon: float):
        """
        Approximate a reverse mapping (lat, lon) → (x, y) by nearest calibration point in GPS space.
        Returns the pixel (x, y) of the nearest calibration point.
        Requires: build_inverse_kdtree() called beforehand.
        """
        if not hasattr(self, "inverse_kdtree"):
            raise RuntimeError("Call build_inverse_kdtree() first to build KDTree.")
        dist, idx = self.inverse_kdtree.query([lat, lon])
        return tuple(self.pixel_coords[idx])  # (x, y) from the calibration set


def main():
    # Path to calibration JSON
    cal_file = os.path.join(os.path.dirname(__file__), "gps_calibration.json")
    if not os.path.exists(cal_file):
        raise FileNotFoundError(f"Calibration file not found: {cal_file}")

    # 1. Load calibration
    pixel_coords, gps_coords = load_calibration(cal_file)

    # 2. Initialize the mapper (build triangulation and affines)
    mapper = PixelToGPSMapper(pixel_coords, gps_coords)

    # 3. Demonstrate pixel → GPS on some test pixels:
    test_pixels = np.array([
        [1376, 710],    # exact calibration point: North Campus Entrance
        [1750, 1500],   # some interior point
        [3000, 5000],   # likely outside the convex hull
    ])
    print("=== Pixel → GPS (piecewise-affine) ===")
    for (x, y) in test_pixels:
        result = mapper.pixel_to_gps(x, y)
        if result is None:
            print(f"Pixel ({x}, {y}) is outside the calibrated region.")
        else:
            lat, lon = result
            print(f"Pixel ({x}, {y}) → Latitude: {lat:.8f}, Longitude: {lon:.8f}")

    # 4. (Optional) Build an inverse KDTree for approximate GPS → Pixel:
    mapper.build_inverse_kdtree()
    test_gps = [
        (41.7490, -72.6890),   # near some calibration cluster
        (41.7430, -72.6910),   # near Clemens roof region
    ]
    print("\n=== Approximate GPS → Pixel (nearest calibration point) ===")
    for (lat, lon) in test_gps:
        px = mapper.approx_gps_to_pixel(lat, lon)
        print(f"GPS ({lat:.8f}, {lon:.8f}) → approx Pixel {px}")

    # 5. (Optional) Batch mapping example:
    batch_result = mapper.batch_pixel_to_gps(test_pixels)
    print("\n=== Batch Pixel → GPS ===")
    for i, (x, y) in enumerate(test_pixels):
        latlon = batch_result[i]
        if np.isnan(latlon).any():
            print(f"Batch Pixel ({x}, {y}) → outside region")
        else:
            print(f"Batch Pixel ({x}, {y}) → (lat, lon) = ({latlon[0]:.8f}, {latlon[1]:.8f})")


if __name__ == "__main__":
    main()
