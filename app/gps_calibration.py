import numpy as np

# Replace with your actual calibration pairs
CALIBRATION_PAIRS = [
    ((41.745061, -72.693923), (479, 849)),
    ((41.744202, -72.692154), (2705, 705)),
    ((41.744944, -72.692830), (1854, 1237)),
    ((41.745999, -72.691888), (1701, 2906)),
]

def calibrate():
    gps = np.array([[lat, lon] for (lat, lon), _ in CALIBRATION_PAIRS])
    pix = np.array([p for _, p in CALIBRATION_PAIRS])
    gps_aug = np.hstack([gps, np.ones((gps.shape[0], 1))])
    M, _, _, _ = np.linalg.lstsq(gps_aug, pix, rcond=None)
    A = M[:2].T
    b = M[2]
    return A, b

A, b = calibrate()

def gps_to_pixel(lat, lon):
    return (A @ np.array([lat, lon]) + b).tolist()
