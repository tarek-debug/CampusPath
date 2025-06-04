# GPS Calibration Guide

This guide explains how to align real world GPS coordinates with the pixels in `trinity_map_original.png`. By providing matching reference points, the application can transform any `(lat, lon)` pair into the correct pixel `(x, y)` position on the map.

## 1. Choose reference locations

Pick at least two easily recognisable spots on campus such as main entrances, statues or intersections. The more reference points you collect the better. Two points allow a simple scale/translation while three or more enable a full affine transform for improved accuracy.

For each location you will record:

1. Pixel coordinates `(x, y)` on the campus map image.
2. GPS coordinates `(lat, lon)` collected from your phone or from Google Maps.

### Recording pixel coordinates

Open `trinity_map_original.png` in an image editor that displays pixel locations or run `fix_coordinates.py` in `data_preparation/` and click on the spot. Note the `(x, y)` values that appear.

### Recording GPS coordinates

On your phone or Google Maps, tap the same physical location and copy the latitude and longitude values. Example: `41.7483, -72.6906`.

## 2. Update `REF_POINTS`

The previous task introduced a constant named `REF_POINTS` which stores the mapping between pixel positions and GPS coordinates. It is defined as a list of tuples like:

```python
REF_POINTS = [
    ((px1, py1), (lat1, lon1)),
    ((px2, py2), (lat2, lon2)),
]
```

Add your collected measurements to this list. Using more than two points will improve the transformation. With at least three entries you can calculate an affine transform that accounts for rotation and scaling differences.

## 3. Verifying the mapping

After updating `REF_POINTS`, run a small script to ensure that converting GPS coordinates back to pixels yields sensible results:

```python
import numpy as np

# assume REF_POINTS is imported

src = np.array([[lat, lon, 1] for (_, (lat, lon)) in REF_POINTS])
dst = np.array([[x, y] for ((x, y), _) in REF_POINTS])
A, _, _, _ = np.linalg.lstsq(src, dst, rcond=None)

def gps_to_pixel(lat, lon):
    x, y = np.dot([lat, lon, 1], A)
    return int(round(x)), int(round(y))

# example usage
print(gps_to_pixel(41.7483, -72.6906))
```

The printed pixel coordinates should correspond closely to the location on the map. Adjust or add more reference points if the error is large.