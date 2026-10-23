# nisar-water viewer

**Live:** https://opera-cal-val.github.io/nisar-water-viewer/ · **Repo:** https://github.com/OPERA-Cal-Val/nisar-water-viewer

A single-page map for comparing **nisar-water** with OPERA **DSWx-NI**, **DSWx-HLS** and **DSWx-S1**, over Esri or Google satellite imagery, with NISAR GCOV and Sentinel-1 backdrops.

- **Your products** (nisar-water and DSWx-NI) are small Cloud-Optimized GeoTIFFs (COGs) published next to the page on GitHub Pages, or in an S3 bucket. The browser reads only the blocks it needs.
- **Streamed from NASA, with no login and nothing stored:**
  - DSWx-HLS, DSWx-S1, Sentinel-1 RTC, HLS true colour and the NISAR GCOV false-colour composite come from [NASA GIBS](https://nasa-gibs.github.io/gibs-api-docs/) as dated map tiles.
  - HLS NDVI and NDWI are computed on request by NASA VEDA's [titiler-cmr](https://openveda.cloud/api/titiler-cmr/api.html).
- **One file:** the whole viewer is `web/index.html`, with no build step and no server code.

## Setup

```bash
pixi install
```

## Everyday use

```bash
pixi run collect          # link source products into data/<example>/ (sources are never modified)
pixi run build            # web-map COGs + OPERA dates -> build/   (or: pixi run build congaree)
pixi run serve            # http://localhost:8000; index.html is re-read on every page load
pixi run site             # assemble site/: exactly what GitHub Pages serves
```

**Three gitignored folders:**

| Folder | Holds |
|---|---|
| `data/<example>/` | **symlinks** to your source files: nisar-water frame WTRs, DSWx-NI `B01_WTR` tiles, manifests, verification tables |
| `build/` | everything the browser reads, including every nisar-water run built so far |
| `site/` | the published subset: the page, catalogs and only the COGs the catalogs point to (hard links into `build/`) |

- **Nothing is copied or changed at the source.** If a source file moves, its link breaks; re-run `collect` once the file is back.
- **Re-running is cheap.** `build` skips existing COGs and reuses the OPERA dates from the previous `catalog.json`. Use `--force` to redo everything.

## What the viewer shows

| Layer | Source | Notes |
|---|---|---|
| nisar-water | `<example>/nisar-water/<run>/<frame>__<date>_WTR.tif` | whole-frame product; 0 not water, 1 open water, 2 inundated vegetation |
| DSWx-NI | `<example>/dswx-ni/v<version>/<frame>__<date>_WTR.tif` | `B01_WTR` only; all tiles of one GCOV acquisition, mosaicked |
| DSWx-HLS | GIBS `OPERA_L3_Dynamic_Surface_Water_Extent-HLS` | best-covered date within ±7 days (below) |
| DSWx-S1 | GIBS `OPERA_L3_Dynamic_Surface_Water_Extent-Sentinel-1` | best-covered date within ±7 days |
| Sentinel-1 RTC | GIBS `OPERA_L2_Radiometric_Terrain_Corrected_SAR_Sentinel-1` | best-covered date within ±7 days; VV/VH false colour |
| HLS RGB | GIBS `HLS_S30_…` over `HLS_L30_Nadir_BRDF_Adjusted_Reflectance` | true colour on the DSWx-HLS date; whichever sensor imaged the site shows |
| HLS NDVI / NDWI | NASA VEDA titiler-cmr (`openveda.cloud/api/titiler-cmr`), the service Worldview uses | computed on request from HLS L30/S30 bands on the DSWx-HLS date, with Worldview's recipes: NDVI `(NIR−red)/(NIR+red)` in brown→green, NDWI `(green−NIR)/(green+NIR)` in pale→dark blue, both stretched −1…+1; drawn from zoom 7 |
| NISAR GCOV RGB | GIBS `NISAR_L2_Geocoded_Polarimetric_Covariance` | same date as nisar-water; co-pol (HH) red/blue, cross-pol (HV) green; ~150 m |

**Colours and the not-water toggle:**
- Colours match GIBS, so the same class looks the same in every layer: open water blue, inundated vegetation green, HAND-masked light grey.
- Not-water is hidden by default so the imagery shows through. **show not-water** (top of the layer panel) draws it as white in every water layer.

**How DSWx-HLS, DSWx-S1 and Sentinel-1 dates are chosen.** For each NISAR scene:
1. **Candidates:** every date within ±7 days with a granule touching the site, from a public CMR search.
2. **Coverage:** for each candidate date, the GIBS tiles the viewer would show are fetched. The share of the **site polygon** with valid data is measured; the polygon is the UMD chip, or the AOI for time-series examples. Cloud does not count for DSWx-HLS.
3. **Choice:** the nearest date with at least 90 % coverage; else the best-covered one; else "no coverage ±7 d".

Each row shows the date, the offset from NISAR and the coverage, e.g. `2026-10-01 (−6.8 d, 100%)`. Example: on 2026-10-08 Congaree is fully cloud-covered in DSWx-HLS, so the viewer shows the clear 2026-10-01 pass.

## Links in the site panel

The **Products** list under each scene links to the exact granules shown:
- **NISAR GCOV and Sentinel-1 RTC** open an ASF Vertex list search for those granules.
- **DSWx-HLS and DSWx-S1** are archived at PO.DAAC, so they open Earthdata Search filtered to those granules.
- **DSWx-NI** lists its MGRS tiles; it is not in any public archive.
- **OSW check (validation sites):** each sensor's score links to the granule that was verified.

## Screenshots for slides

**Save PNG** writes the map at screen resolution, with a title line, a legend and imagery credits.

**File names** are tokens joined by `_`:

`<top layer>_<frame or MGRS tile>_<acquisition time>_<site>_<NE lat>_<NE lon>.png`

- **Top layer:** the highest visible layer, for example `nisar-water`, `DSWx-NI`, `DSWx-HLS`, `DSWx-S1`, `Sentinel-1-RTC` or `NISAR-GCOV-RGB`.
- **Frame or tile, and time:**
  - nisar-water and GCOV: the NISAR frame and the GCOV start time.
  - DSWx layers: the MGRS tile under the centre of the view and that granule's time.
  - Sentinel-1: the burst ID and time.
- **Site:** spaces become `-` and accents are dropped.
- **NE lat / NE lon:** the upper-right corner of the view, to 1 decimal.

For example:
- `nisar-water_T119_F019_A_20261008T103833Z_Congaree-National-Park-Wilderness-SC_34.1_-80.6.png`
- `DSWx-NI_T20HLJ_20260622T101936Z_3_4-Cordoba-Argentina_-33.1_-64.0.png`
- With every layer off, the name starts with the basemap: `Esri-World-Imagery_<site>_<lat>_<lon>.png`.

**Tips:**
- The URL keeps the example, site, date, layers, basemap and camera, so a bookmarked view comes back exactly.
- For sharper images, zoom the browser out (⌘−) and enlarge the window before saving.

## Publishing

The site is deployed by a GitHub Action (`.github/workflows/pages.yml`):

| Branch | Holds |
|---|---|
| `main` | the code, including `web/index.html` |
| `gh-pages` | the catalogs and COGs, i.e. the contents of `site/` after `pixi run site` |

A push to either branch rebuilds the site: `index.html` from `main`, the data from `gh-pages`. So:
- **viewer changes** → push `main`;
- **new data** → `pixi run collect && pixi run build && pixi run site`, then commit and push `site/` (its own git repo) to `gh-pages`.

Where the data lives is one setting in `examples.toml`:

```toml
[site]
pages_url = "https://opera-cal-val.github.io/nisar-water-viewer/"
data = "pages"      # "pages": data served next to index.html; "s3": data read from [bucket]
```

**`data = "pages"` (default):** the data goes in `site/`. It's about 500 MB today, against GitHub Pages' 1 GB limit.

**`data = "s3"`:**
- `site/` holds only `index.html`, and `pixi run upload` syncs `build/` to the bucket.
- The bucket needs public-read objects and a CORS rule allowing the Pages origin. A page on `github.io` cannot read from `amazonaws.com` without that rule, and nothing client-side gets around it.

Everything published is readable by anyone with the URL, including DSWx-NI and unreleased nisar-water runs.

**People who want to change the viewer:**
1. Clone the repo and run `pixi install`.
2. Get the published data with `git clone -b gh-pages --depth 1 <repo> build`.
3. Run `pixi run serve` and edit `web/index.html`; changes show on the next reload.

## Where the data comes from

`collect` links the sources listed in `examples.toml` into `data/<example>/`:

| In `data/<example>/` | Source |
|---|---|
| `scenes.parquet`, `aoi.geojson` | `nisar-water/examples/<example>/` |
| `nisar-water/<run>/ni-water_*_WTR.tif` | `nisar-water/examples/<example>/out/*/frame/` (frame products only) |
| `dswx-ni/<MGRS set>/<date>/*_B01_WTR.tif` | validation: `DSWx-Requirement-Verification-v2/data/.../calval_openwater/Good`; Congaree: `~/Desktop/congaree_opera_dswx-ni` |
| `tables/` (validation only) | `umd_chips.geojson`, plus the `ni_table`, `products` and `results` parquet files from `dswx_out_analysis/2026/` |

**How scenes are matched:**
- A *scene* is one NISAR frame on one date: one row of `scenes.parquet`.
- nisar-water is matched by frame ID and date in its file name.
- DSWx-NI is matched by acquisition start time, the first timestamp in its file name. All tiles of that acquisition are mosaicked, across MGRS sets and UTM zones.
- When two DSWx-NI deliveries cover one acquisition, the one with the newest processing time wins.

**The validation join:**
- The key is the NISAR GCOV granule ID.
- `ni_table.parquet` maps each UMD chip to its granule and GCOV quality. Only `Good` is kept, leaving 74 sites.
- `results.parquet` gives the OSW accuracy, pass/fail and the granule verified for each sensor.
- Site labels add state/province and country from Natural Earth admin-1, downloaded once to `data/`.

`notebooks/build_catalog.ipynb` walks through these steps for any example.

## Adding an example (e.g. Sacramento Valley)

1. **In nisar-water:**
   - Create `examples/<name>/aoi.geojson` with `name` and `state` columns.
   - Run `examples/map_frames.py prepare <name>`.
   - Run the example on edge, then pull the WTR files back with `examples/rsync_gattaca2.sh`.
2. **Add a block to `examples.toml`.** `dswx_ni` is optional and can be any folder; only its `*_B01_WTR.tif` files are used.
   ```toml
   [examples.<name>]
   title = "Human-readable title"
   description = "One sentence for the panel."
   kind = "timeseries"

   [examples.<name>.sources]
   nisar_water = "../nisar-water/examples/<name>"
   dswx_ni = "~/somewhere/opera_dswx-ni"
   ```
3. **Build and check:** `pixi run collect <name> && pixi run build <name>`, then `pixi run serve`.
4. **Publish:** `pixi run site` prints the published size. Keep it under 1 GB, or switch to `data = "s3"`.

**The viewer's contract with nisar-water** is three things:
- the path `out/<frame_id>__<YYYY-MM-DD>/frame/ni-water_*_WTR.tif`;
- the GeoTIFF tags `software_version` and `git_sha`;
- `scenes.parquet` with the columns `granule_id`, `frame_id`, `direction`, `date` and `acq_dt`.

## nisar-water runs and versions

**Run folders.** Every product is filed under a *run* folder named from its own tags:
- `v0.2.0` for a clean release built from a git tag;
- `dev-<git_sha>` otherwise. The current products are `dev-52118db`.

**Choosing a run.** Runs never overwrite each other. `build` uses the newest run (by `created_utc`) unless you pass `--run dev-52118db`.

**To cut a release:**
1. Commit, then `git tag v0.2.0 && git push --follow-tags`.
2. On edge, run `git pull`, then `pixi reinstall nisar-water`. The installed package only sees the tag after the reinstall.
3. Check that `python -c "import nisar_water; print(nisar_water.__version__)"` prints `0.2.0`.

The current products show why step 2 matters. They say `software_version 0.0.1.dev2+g6289fc42c`, but `git_sha 52118db`.

## GIBS quirks (checked October 2026)

- **NISAR GCOV RGB is only reliable up to zoom 10 (~150 m).** At zoom 11–13, GIBS often serves corrupted tiles (RGB data labelled as paletted, or bytes from other layers), and identical requests can return different bytes. The viewer caps that layer at zoom 10 and lets the map upsample.
- **DSWx-S1 occasionally returns a broken tile.** The viewer checks each GIBS tile's PNG type against what its layer should send. On a mismatch it retries twice, then falls back to the parent tile. The coverage check measures at zoom ≤ 10.
- **The GCOV composite can't be split into separate HH and HV images.** GIBS serves only the colour picture.
- **Each GIBS date is one UTC day's mosaic,** which is why coverage is measured on that mosaic rather than on granule footprints.

## Layout

```text
examples.toml   examples, their source folders, site + bucket settings
main.py         click CLI: collect, build, serve, site, upload
collect.py      link source products into data/<example>/
catalog.py      joins -> catalog.json, sites.geojson
opera.py        CMR search + coverage-based choice of DSWx-HLS / DSWx-S1 / RTC-S1 dates
gibs.py         GIBS tiles: fetch, validate, decode, coverage of a polygon
rasters.py      gdal.Warp -> EPSG:3857 COG on the web-map tile grid
pages.py        assemble site/ (the gh-pages branch)
web/index.html  the viewer (MapLibre GL + maplibre-cog-protocol from a CDN)
.github/workflows/pages.yml   deploy main + gh-pages to GitHub Pages
notebooks/      the joins, step by step
```
