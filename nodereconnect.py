# save as connect_lines.py
import json
import math
from collections import defaultdict
from pathlib import Path

# CONFIG
TOLERANCE_METERS = 5.0    # default snapping / auto-connect tolerance (meters)
AUTO_CONNECT = True       # add short connecting segments between near nodes
INPUT = "map/map.geojson"
OUTPUT = "map.connected.geojson"

# haversine distance in meters
def haversine_m(a, b):
    lat1, lon1 = a
    lat2, lon2 = b
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(x))

# build spatial grid to speed up nearest neighbor lookups
def grid_key(lat, lon, cell_size_deg):
    return (int(lat / cell_size_deg), int(lon / cell_size_deg))

def load_geojson(path):
    return json.loads(Path(path).read_text())

def save_geojson(obj, path):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2))

def collect_lines(features):
    lines = []
    for feat in features:
        geom = feat.get("geometry") or {}
        if geom.get("type") == "LineString":
            coords = geom.get("coordinates", [])
            # convert to (lat, lon)
            latlon = [(c[1], c[0]) for c in coords]
            lines.append((feat, latlon))
    return lines

def snap_and_rebuild(lines, tol_m):
    # cell size (deg) roughly based on latitude for ~tol_m distance
    cell_deg = tol_m / 111320.0  # approx degrees per meter for latitude
    nodes = []          # representative node coords (lat, lon)
    rep_index = {}      # maps original (lat,lon) -> index in nodes
    grid = defaultdict(list)

    def find_or_add(p):
        lat, lon = p
        key = grid_key(lat, lon, cell_deg)
        candidates = []
        # check neighbor cells
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                candidates.extend(grid[(key[0]+dx, key[1]+dy)])
        # find nearest candidate within tol
        best = None
        best_d = float('inf')
        for i in candidates:
            d = haversine_m(nodes[i], p)
            if d < best_d:
                best_d = d
                best = i
        if best is not None and best_d <= tol_m:
            return best
        # else add new node
        idx = len(nodes)
        nodes.append(p)
        grid[key].append(idx)
        return idx

    # map all coordinates to representative nodes
    line_node_indices = []
    for feat, coords in lines:
        idxs = []
        for p in coords:
            idx = find_or_add(p)
            idxs.append(idx)
        # remove consecutive duplicates
        dedup = []
        for idv in idxs:
            if not dedup or dedup[-1] != idv:
                dedup.append(idv)
        if len(dedup) >= 2:
            line_node_indices.append((feat, dedup))
    return nodes, line_node_indices

def rebuild_features(original_features, nodes, line_node_indices, tol_m, auto_connect=True):
    # make a shallow copy of features excluding the old LineStrings we will replace
    out_features = []
    # keep non-LineString features as-is
    for feat in original_features:
        if feat.get("geometry", {}).get("type") != "LineString":
            out_features.append(feat)

    # add rebuilt LineStrings (using snapped node coords)
    existing_edges = set()
    for feat, idxs in line_node_indices:
        coords = [[nodes[i][1], nodes[i][0]] for i in idxs]  # [lon, lat]
        out_features.append({
            "type": "Feature",
            "properties": feat.get("properties", {}),
            "geometry": {"type": "LineString", "coordinates": coords}
        })
        # store edges for auto-connect check
        for a,b in zip(idxs, idxs[1:]):
            existing_edges.add(tuple(sorted((a,b))))

    # optionally auto-connect nodes within tol_m that are not already edges
    if auto_connect:
        n = len(nodes)
        # naive pairwise; for big datasets you can optimize with grid again
        for i in range(n):
            for j in range(i+1, n):
                if (i,j) in existing_edges:
                    continue
                d = haversine_m(nodes[i], nodes[j])
                if d <= tol_m:
                    # add a connecting LineString feature
                    out_features.append({
                        "type": "Feature",
                        "properties": {"_auto_connect": True, "distance_m": d},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [nodes[i][1], nodes[i][0]],
                                [nodes[j][1], nodes[j][0]]
                            ]
                        }
                    })
                    existing_edges.add((i,j))
    return {
        "type": "FeatureCollection",
        "features": out_features
    }

def process(path_in, path_out, tol_m=TOLERANCE_METERS, auto_connect=AUTO_CONNECT):
    data = load_geojson(path_in)
    features = data.get("features", [])
    lines = collect_lines(features)
    print(f"Found {len(lines)} LineString features.")
    nodes, line_node_indices = snap_and_rebuild(lines, tol_m)
    print(f"Unique snapped nodes: {len(nodes)}")
    out = rebuild_features(features, nodes, line_node_indices, tol_m, auto_connect)
    save_geojson(out, path_out)
    print(f"Saved fixed GeoJSON to {path_out}")

if __name__ == "__main__":
    # run
    process(INPUT, OUTPUT, TOLERANCE_METERS, AUTO_CONNECT)
