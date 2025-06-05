#!/usr/bin/env python3
"""
piecewise_affine_inverse.py

Builds a piecewise‐affine pixel<->GPS mapper WITHOUT using matplotlib Triangulation.
Instead, gps_to_pixel(lat,lon) simply loops over every triangle, checks barycentric,
and returns the exact inverse if found.

Dependencies:
    numpy, scipy, pickle, json
"""

import json
import pickle
import os

import numpy as np
from scipy.spatial import Delaunay


def load_calibration(cal_file):
    """
    Load calibration points from a JSON file.  Expects a list of objects:
        [ {"x": <float>, "y": <float>, "lat": <float>, "lon": <float>},  … ]
    Returns:
        pixel_pts: np.ndarray shape (N,2)  = [[x1,y1], [x2,y2], …]
        gps_pts:   np.ndarray shape (N,2)  = [[lat1,lon1], [lat2,lon2], …]
    """
    with open(cal_file, "r") as f:
        data = json.load(f)

    pix_list = []
    gps_list = []
    for e in data:
        if "x" not in e or "y" not in e or "lat" not in e or "lon" not in e:
            raise KeyError(f"Calibration entry missing keys: {e}")
        pix_list.append([float(e["x"]), float(e["y"])])
        gps_list.append([float(e["lat"]), float(e["lon"])])
    pixel_pts = np.array(pix_list, dtype=float)
    gps_pts   = np.array(gps_list, dtype=float)
    return pixel_pts, gps_pts


def build_forward_affines(pixel_pts, gps_pts):
    """
    Build a Delaunay triangulation on pixel_pts, then compute per-triangle
    affine maps (A_i, b_i) so that:  (x,y) → (lat,lon).

    Returns:
        delaunay_pixel: scipy.spatial.Delaunay
        affines:       list of length T, each is dict { 'verts': (i0,i1,i2), 'A':2×2, 'b':2 }
        triangles:     np.ndarray shape (T,3) = delaunay_pixel.simplices
    """
    delaunay_pixel = Delaunay(pixel_pts)
    triangles = delaunay_pixel.simplices   # shape (T,3)

    affines = []
    for simplex in triangles:
        P = pixel_pts[simplex]  # shape (3,2)
        G = gps_pts[simplex]    # shape (3,2)

        # Build X and Y:
        #   X @ Mᵀ = Y,  where X is 3×3 = [[x0,y0,1],[x1,y1,1],[x2,y2,1]]
        #         Y is 3×2 = [[lat0,lon0],[lat1,lon1],[lat2,lon2]]
        X = np.vstack([
            [P[0, 0], P[0, 1], 1.0],
            [P[1, 0], P[1, 1], 1.0],
            [P[2, 0], P[2, 1], 1.0],
        ])  # (3×3)
        Y = G  # (3×2)

        X_inv = np.linalg.inv(X)       # (3×3)
        M = (X_inv @ Y).T              # (2×3)
        A = M[:, :2]                   # (2×2)
        b = M[:, 2]                    # (2,)
        affines.append({"verts": simplex.copy(), "A": A.copy(), "b": b.copy()})

    return delaunay_pixel, affines, triangles.copy()


class PiecewiseAffineMapper:
    """
    Encapsulates a bidirectional piecewise‐affine mapping:
      - pixel_to_gps(x,y)  : (lat,lon) exactly
      - gps_to_pixel(lat,lon) : (x,y) exactly, by looping over every triangle

    Internally stores:
      self.pixel_pts
      self.gps_pts
      self.delaunay_pixel
      self.affines          (list of per-triangle dicts)
      self.triangles        (T×3 array of indices)
      self._gps_bboxes      (T×4 array of [min_lat, max_lat, min_lon, max_lon]), for quick pruning
    """

    def __init__(self, pixel_pts: np.ndarray, gps_pts: np.ndarray):
        self.pixel_pts = pixel_pts.copy()
        self.gps_pts   = gps_pts.copy()

        # 1) Build forward Delaunay + per-triangle affines
        self.delaunay_pixel, self.affines, self.triangles = build_forward_affines(self.pixel_pts, self.gps_pts)

        # 2) For gps_to_pixel, precompute each triangle’s GPS‐bounding box:
        #    so that we can quickly skip triangles whose bounding box does NOT contain (lat,lon).
        T = self.triangles.shape[0]
        self._gps_bboxes = np.zeros((T, 4), dtype=float)
        # Columns will be: [min_lat, max_lat, min_lon, max_lon]
        for i in range(T):
            (i0, i1, i2) = self.triangles[i]
            G0 = self.gps_pts[i0]
            G1 = self.gps_pts[i1]
            G2 = self.gps_pts[i2]
            lats = np.array([G0[0], G1[0], G2[0]])
            lons = np.array([G0[1], G1[1], G2[1]])
            self._gps_bboxes[i, 0] = lats.min()
            self._gps_bboxes[i, 1] = lats.max()
            self._gps_bboxes[i, 2] = lons.min()
            self._gps_bboxes[i, 3] = lons.max()

    def pixel_to_gps(self, x: float, y: float):
        """
        Forward mapping: (x,y) → (lat,lon).  Returns None if outside convex hull.
        """
        tri_idx = int(self.delaunay_pixel.find_simplex([[x, y]])[0])
        if tri_idx < 0:
            return None
        A = self.affines[tri_idx]["A"]   # (2×2)
        b = self.affines[tri_idx]["b"]   # (2,)
        latlon = A.dot(np.array([x, y], dtype=float)) + b  # (2,)
        return float(latlon[0]), float(latlon[1])

    def gps_to_pixel(self, lat: float, lon: float):
        """
        True inverse: (lat,lon) → (x,y) exactly.  
        We loop over every triangle, do a quick bounding-box check, then compute barycentric.
        Returns None if (lat,lon) is outside the convex hull of all GPS-calibration points.
        """
        # 1) Quick bounding-box prune: find all triangles whose [min_lat, max_lat]×[min_lon,max_lon]
        #    contains (lat, lon).  Only those can possibly contain the point. 
        #    This cuts down the number of barycentric tests.
        #    If T is small (<500), you can skip this bounding-box step and just loop directly.
        candidates = []
        bboxes = self._gps_bboxes
        # We can vectorize the bbox check for speed:
        mask_lat = (bboxes[:, 0] <= lat) & (lat <= bboxes[:, 1])
        mask_lon = (bboxes[:, 2] <= lon) & (lon <= bboxes[:, 3])
        bbox_hits = np.where(mask_lat & mask_lon)[0]
        if bbox_hits.size == 0:
            # No triangle even has (lat,lon) in its axis‐aligned bbox
            return None

        # 2) For each candidate triangle, compute barycentric coords in GPS‐space:
        for tri_idx in bbox_hits:
            i0, i1, i2 = self.triangles[tri_idx]
            G0 = self.gps_pts[i0]  # (lat0, lon0)
            G1 = self.gps_pts[i1]
            G2 = self.gps_pts[i2]

            # Build 2×2 matrix [G1–G0 , G2–G0] and Δ = [lat–lat0, lon–lon0]
            Mgps = np.array([
                [G1[0] - G0[0],  G2[0] - G0[0]],
                [G1[1] - G0[1],  G2[1] - G0[1]]
            ], dtype=float)
            Δ = np.array([lat - G0[0], lon - G0[1]], dtype=float)

            # Solve [β; γ] = Mgps^{-1} × Δ
            # If Mgps is singular (zero‐area GPS‐triangle), skip
            det = Mgps[0, 0] * Mgps[1, 1] - Mgps[0, 1] * Mgps[1, 0]
            if abs(det) < 1e-12:
                # Degenerate (collinear) or extremely skinny triangle in GPS‐space
                continue

            invM = np.linalg.inv(Mgps)  # (2×2)
            beta_gamma = invM.dot(Δ)    # shape (2,)
            β, γ = float(beta_gamma[0]), float(beta_gamma[1])
            α = 1.0 - β - γ

            # Check if inside (allow a small negative tolerance for numerical noise)
            if α < -1e-9 or β < -1e-9 or γ < -1e-9:
                continue

            # 3) If we reach here, (lat,lon) is inside GPS‐triangle `tri_idx`.  Recover pixel by barycentric:
            P0 = self.pixel_pts[i0]
            P1 = self.pixel_pts[i1]
            P2 = self.pixel_pts[i2]

            x = α * P0[0] + β * P1[0] + γ * P2[0]
            y = α * P0[1] + β * P1[1] + γ * P2[1]
            return float(x), float(y)

        # If no candidate triangle actually contained (lat,lon), then it's outside the hull:
        return None

    def save(self, filename: str):
        """
        Serialize this entire mapper to disk via pickle.
        That includes:
          - pixel_pts, gps_pts
          - delaunay_pixel
          - affines (list of per-triangle dicts)
          - triangles (T×3)
          - _gps_bboxes (T×4)
        """
        with open(filename, "wb") as f:
            pickle.dump(self, f)

    @classmethod
    def load(cls, filename: str):
        """
        Load a previously saved mapper from disk:
            mapper = PiecewiseAffineMapper.load("mapper.pkl")
        """
        with open(filename, "rb") as f:
            obj = pickle.load(f)
        return obj


if __name__ == "__main__":
    # Example usage:

    # 1) Build from scratch
    cal_file = os.path.join(os.path.dirname(__file__), "gps_calibration.json")
    pixel_pts, gps_pts = load_calibration(cal_file)

    mapper = PiecewiseAffineMapper(pixel_pts, gps_pts)

    # 2) Test a few forward lookups:
    print(">>> Forward (pixel→GPS):")
    for (x, y) in [(pixel_pts[0,0], pixel_pts[0,1]), (1500, 2000)]:
        out = mapper.pixel_to_gps(x, y)
        print(f"  Pixel=({x:.1f},{y:.1f}) → {out}")

    # 3) Test a few inverse lookups:
    print("\n>>> Inverse (GPS→pixel):")
    # a) exactly on a calibration point:
    lat0, lon0 = gps_pts[0,0], gps_pts[0,1]
    out0 = mapper.gps_to_pixel(lat0, lon0)
    print(f"  GPS=({lat0:.6f},{lon0:.6f}) → Pixel={out0}")

    # b) the forward-mapped point (1500,2000):
    forward_latlon = mapper.pixel_to_gps(1500, 2000)
    out1 = mapper.gps_to_pixel(forward_latlon[0], forward_latlon[1])
    print(f"  GPS={forward_latlon} → Pixel={out1}")

    # c) slightly off a calibration point:
    out2 = mapper.gps_to_pixel(lat0 + 1e-4, lon0 + 1e-4)
    print(f"  GPS=({lat0+1e-4:.6f},{lon0+1e-4:.6f}) → Pixel={out2}")

    # 4) Save to disk
    pkl_path = os.path.join(os.path.dirname(__file__), "mapper.pkl")
    mapper.save(pkl_path)
    print(f"\nSaved mapper to {pkl_path}")

    # 5) Demonstrate loading it again:
    mapper2 = PiecewiseAffineMapper.load(pkl_path)
    test = mapper2.gps_to_pixel(gps_pts[0,0], gps_pts[0,1])
    print("Loaded mapper from disk.  Inverse test:", test)
