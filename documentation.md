# Documentation

## 1. Overview
This project builds a geo-behavior feature layer by identifying whether a customer login event occurred inside a commercial mall in Hanoi, using OpenStreetMap (OSM) data.

The output supports downstream ML tasks such as churn prediction, next-best-offer, lifestyle segmentation, and co-brand targeting.

## 2. Business Objective
Input login schema:

```text
cusid | timestamp | lat | lon
```

Enrichment question:

> Was the customer inside a commercial mall at the time of login?

## 3. Data Sources
### 3.1 Customer Login Data
- `cusid`: customer id
- `timestamp`: login time
- `lat`: latitude
- `lon`: longitude

### 3.2 OpenStreetMap via Overpass API
Tags queried:
- `building=mall`
- `shop=mall`

Hanoi bbox:
- South: `20.90`
- West: `105.70`
- North: `21.20`
- East: `106.05`

## 4. Pipeline Architecture
### Step 1: Fetch Mall Polygons
Query Overpass API by bbox and parse OSM ways into polygons.

### Step 2: Parse Geometry
Build GeoDataFrame in `EPSG:4326` with columns:
- `name`
- `brand`
- `operator`
- `tags`
- `geometry`

### Step 3: Mall Filtering
Apply keyword filtering (`name/brand/operator`) and cap output using `MAX_MALLS`.
Fallback to largest polygons when keyword filter is empty.

### Step 4: Spatial Join
- Reproject to `EPSG:32648`
- Buffer polygons by GPS tolerance
- `geopandas.sjoin(..., predicate="within")`
- Output label: `is_in_mall`

### Step 5: Time Binning
Timestamps are binned into:
- `morning`: 05:00-10:59
- `noon`: 11:00-12:59
- `afternoon`: 13:00-17:59
- `night`: 18:00-04:59

## 5. Caching Strategy
Config flags:
- `USE_CACHE`
- `FORCE_REFRESH_CACHE`
- `CACHE_FILE`

Behavior:
1. If cache exists and `USE_CACHE=True` and `FORCE_REFRESH_CACHE=False`: load cache.
2. Else: call Overpass API and write cache JSON.

Cache JSON contains:
- `source`
- `saved_at_utc`
- `data` (raw Overpass response)

## 6. Visualization
Generated file: `storage/hanoi_mall_logins_map.html`

Features:
- Mall polygons with tooltip (`name`, `brand`, `operator`)
- Search box for mall name
- Layer control for time-bin overlays
- MarkerCluster per time bin
- Red markers for in-mall logins

## 7. Runtime Variables
Defined at the top of `main_python.py`:

```python
MAX_MALLS = 3
MALL_KEYWORDS = ("aeon", "vincom", "lotte")
USE_CACHE = True
FORCE_REFRESH_CACHE = False
CACHE_FILE = Path("storage/overpass_hanoi_malls_cache.json")
```

## 8. Production Notes
- Overpass is not suitable for low-latency real-time pipelines.
- Recommended production flow:
  1. Periodically refresh mall polygons offline
  2. Store in internal object storage
  3. Load static geometries in feature jobs
