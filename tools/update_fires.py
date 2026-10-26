"""Regional FIRMS snapshots. Secrets stay in the Actions environment."""
import csv
import io
import json
import math
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ["VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"]
RADIUS_M = 5000
DAYS = 3  # API uses calendar days; filter to an actual rolling 48 hours below.
M_PER_DEG = 111_320


def rings(geom):
    return [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]


def inside(poly, lon, lat):
    def in_ring(ring):
        c = False
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > lat) != (y2 > lat) and lon < (x2-x1)*(lat-y1)/(y2-y1)+x1:
                c = not c
        return c
    return in_ring(poly[0]) and not any(in_ring(h) for h in poly[1:])


def contains(geometry, lat, lon):
    return any(inside(poly, lon, lat) for poly in rings(geometry))


def dist_m(geom, lat, lon):
    kx = M_PER_DEG * math.cos(math.radians(lat))
    best = math.inf
    for poly in rings(geom):
        if inside(poly, lon, lat):
            return 0.0
        for ring in poly:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:]+ring[:1]):
                ax, ay = (x1-lon)*kx, (y1-lat)*M_PER_DEG
                dx, dy = (x2-x1)*kx, (y2-y1)*M_PER_DEG
                t = 0 if dx == dy == 0 else max(0, min(1, -(ax*dx+ay*dy)/(dx*dx+dy*dy)))
                best = min(best, math.hypot(ax+t*dx, ay+t*dy))
    return best


def parse_points(text, source, now):
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff").strip()))
    required = {"latitude", "longitude", "acq_date", "acq_time", "satellite"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("NASA returned an invalid CSV response")
    points = []
    for row in reader:
        # Reject malformed snapshots instead of reporting a false zero.
        lat, lon = float(row["latitude"]), float(row["longitude"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Invalid coordinates")
        t = row["acq_time"].zfill(4)
        acquired = datetime.strptime(row["acq_date"]+t, "%Y-%m-%d%H%M").replace(tzinfo=timezone.utc)
        if not now-timedelta(hours=48) <= acquired <= now+timedelta(minutes=10):
            continue
        points.append({"lat": lat, "lon": lon, "acquired": acquired.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "satellite": {"N20":"NOAA-20", "N21":"NOAA-21"}.get(row["satellite"], row["satellite"]),
            "confidence": {"l":"низкая", "n":"средняя", "h":"высокая"}.get(row.get("confidence"), row.get("confidence", "—")),
            "frp": float(row.get("frp") or 0), "daynight": row.get("daynight", ""), "source": source})
    return points


def fetch_points(key, source, region, now):
    c = region["coverage"]
    bbox = f"{c['min_lon']},{c['min_lat']},{c['max_lon']},{c['max_lat']}"
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{bbox}/{DAYS}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return parse_points(response.read().decode("utf-8"), source, now)
        except Exception:
            # Do not log exceptions containing the authenticated URL.
            if attempt == 2:
                raise RuntimeError("NASA request failed") from None
            time.sleep(2**attempt)


def enrich(points, region, zones):
    found = {}
    envelopes = []
    for z in zones:
        pts = [p for poly in rings(z['geometry']) for ring in poly for p in ring]
        envelopes.append((z,min(p[0] for p in pts),min(p[1] for p in pts),max(p[0] for p in pts),max(p[1] for p in pts)))
    for p in points:
        if not contains(region["geometry"], p["lat"], p["lon"]):
            continue
        near = None
        kx = M_PER_DEG * math.cos(math.radians(p['lat']))
        for z,west,south,east,north in envelopes:
            dx = max(west-p['lon'],0,p['lon']-east)*kx
            dy = max(south-p['lat'],0,p['lat']-north)*M_PER_DEG
            if math.hypot(dx,dy)>RADIUS_M:
                continue
            distance = dist_m(z['geometry'],p['lat'],p['lon'])
            if distance<=RADIUS_M and (near is None or distance<near[0]):
                near = distance,z
        f = dict(p, region_id=region["id"], near_oopt=bool(near and near[0]<=RADIUS_M))
        if near:
            distance, zone = near
            f.update(zone_id=zone["id"], zone_name=zone["name"], distance_m=round(distance), zone_precise=zone["precise"])
        key = (f["lat"], f["lon"], f["acquired"], f["satellite"])
        found[key] = f
    return sorted(found.values(), key=lambda f:f["acquired"], reverse=True)


def update(data, old, key, fetcher=fetch_points, now=None):
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshots, combined = {}, []
    for region in data["regions"]:
        rid = region["id"]
        previous = old.get("regions", {}).get(rid, {})
        try:
            points = []
            for source in SOURCES:
                points.extend(fetcher(key, source, region, now))
            zones = [z for z in data["zones"] if rid in z["region_ids"]]
            fires = enrich(points, region, zones)
            snapshot = {"status":"ok", "updated":stamp, "attempted":stamp, "checked_points":len(fires), "fires":fires}
        except Exception:
            snapshot = {**previous, "status":"error", "attempted":stamp,
                "error":"Не удалось обновить данные NASA. Показаны последние полученные данные, если они есть.",
                "fires":previous.get("fires", [])}
        snapshots[rid] = snapshot
        combined.extend(snapshot["fires"])
    return {"source":"NASA FIRMS: NOAA-20 и NOAA-21, последние 48 часов", "radius_m":RADIUS_M,
        "updated":stamp, "regions":snapshots, "checked_points":sum(len(s["fires"]) for s in snapshots.values()), "fires":combined}


def main():
    key = os.environ["FIRMS_MAP_KEY"].strip()
    if not key:
        raise SystemExit("FIRMS_MAP_KEY is not configured")
    data = json.loads((ROOT/"data"/"zones.json").read_text(encoding="utf-8"))
    path = ROOT/"data"/"fires.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    out = update(data, old, key)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(path)
    for rid, snapshot in out["regions"].items():
        print(rid, snapshot["status"], len(snapshot["fires"]), "points")
    # Commit partial/error snapshots too, so the UI can show failure, not a false all-clear.


if __name__ == "__main__":
    main()
