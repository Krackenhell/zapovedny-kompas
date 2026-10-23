"""Термоточки NASA FIRMS у ООПТ Ишимского округа → data/fires.json.

Запускается GitHub Actions раз в час (.github/workflows/fires.yml).
Ключ берётся из секрета FIRMS_MAP_KEY. Без внешних библиотек.
"""
import csv
import io
import json
import math
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"]
RADIUS_M = 5000
DAYS = 2
M_PER_DEG = 111_320


def rings(geom):
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    return polys


def inside(poly, lon, lat):
    def in_ring(ring):
        c = False
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                c = not c
        return c
    return in_ring(poly[0]) and not any(in_ring(h) for h in poly[1:])


def dist_m(geom, lat, lon):
    kx = M_PER_DEG * math.cos(math.radians(lat))
    best = math.inf
    for poly in rings(geom):
        if inside(poly, lon, lat):
            return 0.0
        for ring in poly:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
                ax, ay = (x1 - lon) * kx, (y1 - lat) * M_PER_DEG
                bx, by = (x2 - lon) * kx, (y2 - lat) * M_PER_DEG
                dx, dy = bx - ax, by - ay
                t = 0 if dx == dy == 0 else max(0, min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
                best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def main():
    key = os.environ["FIRMS_MAP_KEY"]
    data = json.loads((ROOT / "data" / "zones.json").read_text(encoding="utf-8"))
    cov = data["coverage"]
    bbox = f"{cov['min_lon'] - 0.1},{cov['min_lat'] - 0.1},{cov['max_lon'] + 0.1},{cov['max_lat'] + 0.1}"
    fires, total = {}, 0
    for src in SOURCES:
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{src}/{bbox}/{DAYS}"
        text = urllib.request.urlopen(url, timeout=60).read().decode()
        for row in csv.DictReader(io.StringIO(text)):
            total += 1
            lat, lon = float(row["latitude"]), float(row["longitude"])
            t = row["acq_time"].zfill(4)
            acquired = f"{row['acq_date']}T{t[:2]}:{t[2:]}:00Z"
            near = min(((dist_m(z["geometry"], lat, lon), z) for z in data["zones"]), key=lambda p: p[0])
            if near[0] > RADIUS_M:
                continue
            k = f"{lat:.3f},{lon:.3f},{acquired}"
            fires[k] = {
                "lat": lat, "lon": lon, "acquired": acquired,
                "satellite": {"N20": "NOAA-20", "N21": "NOAA-21"}.get(row["satellite"], row["satellite"]),
                "confidence": {"l": "низкая", "n": "средняя", "h": "высокая"}.get(row["confidence"], row["confidence"]),
                "frp": float(row["frp"] or 0), "daynight": row.get("daynight", ""),
                "zone_id": near[1]["id"], "zone_name": near[1]["name"], "distance_m": round(near[0]),
            }
    out = {
        "source": "NASA FIRMS: " + ", ".join(SOURCES) + f", последние {DAYS * 24} ч",
        "radius_m": RADIUS_M, "checked_points": total,
        "fires": sorted(fires.values(), key=lambda f: f["acquired"], reverse=True),
    }
    path = ROOT / "data" / "fires.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if {k: v for k, v in old.items() if k != "updated"} != out:
        out["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print("обновлено:", len(fires), "у ООПТ из", total)
    else:
        print("без изменений:", len(fires), "у ООПТ из", total)


if __name__ == "__main__":
    main()
