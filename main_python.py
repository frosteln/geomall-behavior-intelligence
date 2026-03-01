import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon, Point
from shapely.ops import unary_union
import folium
from folium.plugins import MarkerCluster
from folium.plugins import Search
from datetime import datetime, timedelta, timezone
import random
import numpy as np
from pathlib import Path
import json

# ---------------------------
# Config (edit these)
# ---------------------------
MAX_MALLS = 3
MALL_KEYWORDS = ("aeon", "vincom", "lotte")
USE_CACHE = True
FORCE_REFRESH_CACHE = False
CACHE_FILE = Path("storage/overpass_hanoi_malls_cache.json")

# ---------------------------
# 0) HTTP helper (Overpass)
# ---------------------------
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

def overpass_query(query: str, timeout=60):
    """
    Execute an Overpass QL query and return JSON.
    Adds a User-Agent header (good practice).
    """
    headers = {
        "User-Agent": "GeoMallFeatureLab/1.0 (contact: internal-analytics@yourbank)"
    }
    r = requests.get(OVERPASS_URL, params={"data": query}, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_overpass_data(query: str, cache_file=CACHE_FILE, use_cache=USE_CACHE, force_refresh=FORCE_REFRESH_CACHE):
    """
    Load Overpass response from local cache when allowed.
    Query API and refresh cache when cache is missing or refresh is forced.
    """
    cache_path = Path(cache_file)

    if use_cache and not force_refresh and cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return payload["data"]

    data = overpass_query(query)
    payload = {
        "source": "overpass-api.de",
        "saved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": data,
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return data

# ---------------------------------------------
# 1) Build Hanoi area correctly (admin_level=4)
# ---------------------------------------------

def build_hanoi_bbox_query():
    # South, West, North, East
    bbox = "20.90,105.70,21.20,106.05"
    
    return f"""
[out:json][timeout:60];
(
  way["building"="mall"]({bbox});
  way["shop"="mall"]({bbox});
  relation["building"="mall"]({bbox});
  relation["shop"="mall"]({bbox});
);
out body;
>;
out skel qt;
"""

# ----------------------------------------------------
# 2) Parse Overpass JSON into polygons (ways + rels)
# ----------------------------------------------------
def parse_polygons(osm_json):
    elements = osm_json["elements"]
    
    nodes = {
        el["id"]: (el["lon"], el["lat"])
        for el in elements if el["type"] == "node"
    }
    
    records = []
    
    for el in elements:
        if el["type"] == "way":
            coords = []
            for nid in el.get("nodes", []):
                if nid in nodes:
                    coords.append(nodes[nid])
            
            if len(coords) >= 4:
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                
                poly = Polygon(coords)
                
                if poly.is_valid:
                    tags = el.get("tags", {})
                    records.append({
                        "name": tags.get("name"),
                        "brand": tags.get("brand"),
                        "operator": tags.get("operator"),
                        "tags": tags,
                        "geometry": poly
                    })

    gdf = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")
    return gdf

# ----------------------------------------------------
# 3) Fetch malls in Hanoi + filter by brand keywords
# ----------------------------------------------------
def fetch_hanoi_malls(
    limit=MAX_MALLS,
    keywords=MALL_KEYWORDS,
    use_cache=USE_CACHE,
    force_refresh=FORCE_REFRESH_CACHE,
    cache_file=CACHE_FILE,
):
    q = build_hanoi_bbox_query()
    data = get_overpass_data(
        q,
        cache_file=cache_file,
        use_cache=use_cache,
        force_refresh=force_refresh,
    )
    mall_gdf = parse_polygons(data)

    # If query returns 0, give diagnostics
    if mall_gdf.empty:
        raise ValueError(
            "No mall polygons returned. Possible causes:\n"
            "- Hanoi boundary relation not matched (name mismatch)\n"
            "- Overpass rate/timeout\n"
            "- OSM tags not present\n"
        )

    # Client-side filter: name/brand/operator contains keyword (case-insensitive)
    def row_match(row):
        text = " ".join([
            str(row.get("name") or ""),
            str(row.get("brand") or ""),
            str(row.get("operator") or "")
        ]).lower()
        return any(k.lower() in text for k in keywords)

    for col in ["name", "brand", "operator"]:
        if col not in mall_gdf.columns:
            mall_gdf[col] = None

    text_cols = (
        mall_gdf[["name", "brand", "operator"]]
        .fillna("")
        .agg(" ".join, axis=1)
        .str.lower()
    )

    mask = text_cols.apply(lambda x: any(k in x for k in keywords))
    filtered = mall_gdf[mask].copy()

    # If brand filter too strict, fallback to top malls by area (largest polygons)
    if filtered.empty:
        # Project to metric CRS (UTM zone for Hanoi ~ EPSG:32648)
        mall_metric = mall_gdf.to_crs(epsg=32648)
        mall_gdf["area_m2"] = mall_metric.geometry.area
        filtered = mall_gdf.sort_values("area_m2", ascending=False).head(limit).copy()
    else:
        filtered = filtered.head(limit).copy()

    # Clean columns with a stable schema even if OSM objects miss some tags
    for col, default in [("name", None), ("brand", None), ("operator", None), ("tags", {})]:
        if col not in filtered.columns:
            filtered[col] = default
    filtered = filtered[["name", "brand", "operator", "tags", "geometry"]].reset_index(drop=True)
    return filtered

# ---------------------------
# 4) Sample login data
# ---------------------------
def _random_point_in_polygon(geom, max_tries=500):
    """
    Rejection-sample a random point inside Polygon/MultiPolygon.
    """
    if geom is None or geom.is_empty:
        return None

    target = geom
    if isinstance(geom, MultiPolygon):
        parts = [g for g in geom.geoms if not g.is_empty and g.area > 0]
        if not parts:
            return None
        areas = np.array([p.area for p in parts], dtype=float)
        probs = areas / areas.sum()
        target = parts[np.random.choice(len(parts), p=probs)]

    minx, miny, maxx, maxy = target.bounds
    for _ in range(max_tries):
        x = np.random.uniform(minx, maxx)
        y = np.random.uniform(miny, maxy)
        p = Point(x, y)
        if target.contains(p):
            return p

    # Fallback if random attempts fail
    return target.representative_point()


def generate_sample_logins(
    n=80,
    users=("C001", "C002", "C003", "C004", "C005"),
    seed=42,
    mall_gdf=None,
    in_mall_ratio=0.35,
):
    np.random.seed(seed)
    random.seed(seed)

    # rough bounding box around Hanoi
    lat_min, lat_max = 20.95, 21.10
    lon_min, lon_max = 105.75, 105.95

    base_time = datetime(2026, 3, 1, 8, 0, 0)
    rows = []
    inside_count = 0
    target_inside = 0
    mall_geoms = []

    if mall_gdf is not None and not mall_gdf.empty:
        mall_geoms = [g for g in mall_gdf.geometry.tolist() if g is not None and not g.is_empty]
        target_inside = min(n, max(0, int(round(n * in_mall_ratio))))

    for i in range(n):
        use_inside = inside_count < target_inside
        point = None

        if use_inside and mall_geoms:
            geom = random.choice(mall_geoms)
            point = _random_point_in_polygon(geom)

        if point is None:
            lon = float(np.random.uniform(lon_min, lon_max))
            lat = float(np.random.uniform(lat_min, lat_max))
        else:
            lon = float(point.x)
            lat = float(point.y)
            inside_count += 1

        rows.append(
            {
                "cusid": random.choice(users),
                "lat": lat,
                "lon": lon,
                "timestamp": base_time + timedelta(minutes=random.randint(0, 7 * 24 * 60)),
            }
        )

    df = pd.DataFrame(rows)
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs="EPSG:4326")
    return gdf

# ---------------------------
# 5) Point-in-polygon join
# ---------------------------
def label_logins_in_malls(login_gdf, mall_gdf, gps_buffer_m=30):

    # Project to metric CRS
    mall_metric = mall_gdf.to_crs(epsg=32648)
    login_metric = login_gdf.to_crs(epsg=32648)

    # Buffer malls in meters
    mall_metric["geometry"] = mall_metric.geometry.buffer(gps_buffer_m)

    # Spatial join
    joined_metric = gpd.sjoin(login_metric, mall_metric, how="left", predicate="within")

    # Convert back to WGS84 for visualization
    joined = joined_metric.to_crs(epsg=4326)

    joined["is_in_mall"] = joined["name"].notna().astype(int)

    return joined


def add_time_bin(df, ts_col="timestamp", out_col="time_bin"):
    """
    Bin timestamps into business-friendly windows.
    """
    ts = pd.to_datetime(df[ts_col], errors="coerce")

    def _bucket(hour):
        if pd.isna(hour):
            return "unknown"
        h = int(hour)
        if 5 <= h < 11:
            return "morning"
        if 11 <= h < 13:
            return "noon"
        if 13 <= h < 18:
            return "afternoon"
        return "night"

    out = df.copy()
    out[out_col] = ts.dt.hour.apply(_bucket)
    return out

# ---------------------------
# 6) Folium visualization
# ---------------------------
def visualize_malls_and_logins(mall_gdf, joined_gdf):
    # Map center (mean of mall centroids if available else Hanoi center-ish)
    if not mall_gdf.empty:
        mall_centroids = mall_gdf.to_crs(epsg=32648).geometry.centroid.to_crs(epsg=4326)
        center = [mall_centroids.y.mean(), mall_centroids.x.mean()]
    else:
        center = [21.03, 105.85]

    m = folium.Map(location=center, zoom_start=12)

    # Add mall polygons with visible outlines + labels
    malls_geojson = None
    if not mall_gdf.empty:
        malls_layer = mall_gdf[["name", "brand", "operator", "geometry"]].copy()
        malls_layer["name"] = malls_layer["name"].fillna("Mall")
        malls_layer["brand"] = malls_layer["brand"].fillna("-")
        malls_layer["operator"] = malls_layer["operator"].fillna("-")
        malls_geojson = folium.GeoJson(
            malls_layer,
            name="Mall Polygons",
            style_function=lambda x: {
                "fillColor": "#2b6cb0",
                "color": "#1a365d",
                "fillOpacity": 0.22,
                "weight": 3,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["name", "brand", "operator"],
                aliases=["Mall", "Brand", "Operator"],
                localize=True,
                sticky=True,
            ),
        ).add_to(m)

    # Search box: quickly zoom to mall by name
    if malls_geojson is not None:
        Search(
            layer=malls_geojson,
            search_label="name",
            geom_type="Polygon",
            placeholder="Search mall name",
            collapsed=False,
        ).add_to(m)

    # Add clustered login points by time bins (toggle in LayerControl)
    working = add_time_bin(joined_gdf, ts_col="timestamp", out_col="time_bin")
    colors = {
        "morning": "#f59e0b",
        "noon": "#2563eb",
        "afternoon": "#ea580c",
        "night": "#7c3aed",
        "unknown": "#6b7280",
    }
    bins = ["morning", "noon", "afternoon", "night", "unknown"]
    groups = {}
    for b in bins:
        fg = folium.FeatureGroup(name=f"Logins - {b.title()}", show=(b != "unknown"))
        fg.add_to(m)
        groups[b] = MarkerCluster(name=f"{b.title()} Cluster").add_to(fg)

    for _, r in working.iterrows():
        bin_name = r.get("time_bin", "unknown")
        if bin_name not in groups:
            bin_name = "unknown"
        base = colors.get(bin_name, "#6b7280")
        color = "red" if r["is_in_mall"] == 1 else base
        popup = folium.Popup(
            f"""
            <b>Customer:</b> {r['cusid']}<br>
            <b>Time:</b> {r['timestamp']}<br>
            <b>Time bin:</b> {bin_name}<br>
            <b>In mall:</b> {r['is_in_mall']}<br>
            <b>Mall:</b> {r.get('name') if pd.notna(r.get('name')) else '-'}
            """,
            max_width=300
        )
        folium.CircleMarker(
            location=[r["lat"], r["lon"]],
            radius=4,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.8,
            popup=popup
        ).add_to(groups[bin_name])

    folium.LayerControl().add_to(m)
    return m


# ---------------------------
# 7) Run end-to-end
# ---------------------------

mall_gdf = fetch_hanoi_malls(
    limit=MAX_MALLS,
    keywords=MALL_KEYWORDS,
    use_cache=USE_CACHE,
    force_refresh=FORCE_REFRESH_CACHE,
    cache_file=CACHE_FILE,
)
print("Malls found (after filtering/fallback):")
print(mall_gdf[["name", "brand", "operator"]])

login_gdf = generate_sample_logins(n=120, mall_gdf=mall_gdf, in_mall_ratio=0.4)
joined = label_logins_in_malls(login_gdf, mall_gdf, gps_buffer_m=30)
joined = add_time_bin(joined, ts_col="timestamp", out_col="time_bin")

print("Sample joined rows:")
print(joined[["cusid","timestamp","time_bin","lat","lon","name","is_in_mall"]].head(10))

print("Mall hit rate:", joined["is_in_mall"].mean())
print("Total mall logins:", joined["is_in_mall"].sum())

mall_map = visualize_malls_and_logins(mall_gdf, joined)
mall_map.save("storage/hanoi_mall_logins_map.html")
print("Saved map: storage/hanoi_mall_logins_map.html")
