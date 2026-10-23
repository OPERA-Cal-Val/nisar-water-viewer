import json
import re
import tomllib
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.request import urlretrieve

import geopandas as gpd
import pandas as pd
from osgeo import gdal

import opera
import rasters


ROOT = Path(__file__).parent
BUILD = ROOT / 'build'
DATA = ROOT / 'data'
WEB = ROOT / 'web' / 'index.html'
ADMIN_URL = 'https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces.zip'
STRATA = {1: 'dry', 2: 'low water', 3: 'medium water', 4: 'high water'}
GIBS_KEYS = ('dswx_hls', 'dswx_s1', 'rtc_s1')
DSWX_NI_NAME = re.compile(
    r'OPERA_L3_DSWx-NI_T(?P<tile>\w{5})_(?P<acq>\d{8}T\d{6})Z_(?P<processed>\d{8}T\d{6})Z_LSAR_30_v(?P<version>.+)_B01_WTR\.tif'
)

Jobs = dict[str, tuple[list[Path], Path]]


def load_config(path: Path = ROOT / 'examples.toml') -> dict:
    return tomllib.loads(path.read_text())


def resolve(path: str) -> Path:
    expanded = Path(path).expanduser()
    return expanded if expanded.is_absolute() else (ROOT / expanded).resolve()


def resolve_sources(sources: dict) -> dict:
    return {k: [resolve(p) for p in v] if isinstance(v, list) else resolve(v) for k, v in sources.items()}


def example_config(name: str) -> dict:
    cfg = load_config()['examples'][name]
    return cfg | {'name': name, 'data': DATA / name, 'sources': resolve_sources(cfg.get('sources', {}))}


def bucket_url() -> str:
    bucket = load_config()['bucket']
    return f'https://{bucket["name"]}.s3.{bucket["region"]}.amazonaws.com/'


def data_on_s3() -> bool:
    return load_config()['site']['data'] == 's3'


def text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def bbox(geometry: object) -> list[float]:
    return [round(v, 5) for v in geometry.bounds]


def slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def scene_key(frame_id: str, date: str) -> str:
    return f'{frame_id}__{date}'


def run_dirs(data_dir: Path) -> list[Path]:
    return sorted(p for p in (data_dir / 'nisar-water').glob('*') if p.is_dir())


def run_created(run_dir: Path) -> str:
    first = next(run_dir.glob('ni-water_*_WTR.tif'), None)
    return rasters.tags(first).get('created_utc', '') if first else ''


def pick_run(data_dir: Path, run: str | None) -> Path | None:
    if run:
        return data_dir / 'nisar-water' / run
    runs = run_dirs(data_dir)
    return max(runs, key=run_created) if runs else None


def find_wtr(run_dir: Path | None, frame_id: str, date: str) -> Path | None:
    if run_dir is None:
        return None
    hits = sorted(run_dir.glob(f'ni-water_{frame_id}_{date.replace("-", "")}T*_WTR.tif'))
    return hits[0] if hits else None


def read_scenes(data_dir: Path, run_dir: Path | None) -> pd.DataFrame:
    scenes = pd.read_parquet(data_dir / 'scenes.parquet').drop_duplicates('granule_id').sort_values('acq_dt')
    return scenes.assign(
        scene=[scene_key(f, d) for f, d in zip(scenes.frame_id, scenes.date)],
        wtr=[find_wtr(run_dir, f, d) for f, d in zip(scenes.frame_id, scenes.date)],
        acq_time=[t.to_pydatetime() for t in scenes.acq_dt],
        acq_key=[f'{t:%Y%m%dT%H%M%S}' for t in scenes.acq_dt],
    ).reset_index(drop=True)


def admin_regions() -> gpd.GeoDataFrame:
    path = DATA / Path(ADMIN_URL).name
    if not path.exists():
        DATA.mkdir(exist_ok=True)
        urlretrieve(ADMIN_URL, path)
    regions = gpd.read_file(path)[['name', 'admin', 'geometry']]
    return regions.rename(columns={'name': 'state', 'admin': 'country'})


def admin_labels(sites: gpd.GeoDataFrame) -> pd.DataFrame:
    points = gpd.GeoDataFrame({'site_id': sites.site_id}, geometry=sites.to_crs(6933).centroid)
    joined = gpd.sjoin_nearest(points, admin_regions().to_crs(6933), how='left').drop_duplicates('site_id')
    return joined[['site_id', 'state', 'country']]


def site_label(site_id: str, state: str | None, country: str | None, strata: str | None) -> str:
    place = ', '.join(p for p in (text(state), text(country)) if p)
    return ' · '.join(p for p in (site_id, place, text(strata)) if p)


def validation_sites(tables: Path) -> gpd.GeoDataFrame:
    chips = gpd.read_file(tables / 'umd_chips.geojson').rename(columns={'SAMPLE_ID': 'site_id', 'STRATA': 'strata'})
    ni = pd.read_parquet(tables / 'ni_table.parquet').query("quality == 'Good'")
    columns = ['site_id', 'quality', 'comments', 'nisar_id', 'track', 'direction', 'status']
    sites = chips[['site_id', 'strata', 'geometry']].merge(ni[columns], on='site_id')
    sites = sites.merge(admin_labels(sites), on='site_id', how='left')
    sites = sites.assign(strata_label=sites.strata.map(STRATA))
    labels = [site_label(*row) for row in zip(sites.site_id, sites.state, sites.country, sites.strata_label)]
    return sites.assign(label=labels).sort_values(['country', 'state', 'site_id']).reset_index(drop=True)


def verification(tables: Path) -> dict[str, dict]:
    results = pd.read_parquet(tables / 'results.parquet')
    return {
        site: {
            r.sensor: {'pass': bool(r.osw_pass), 'acc': round(float(r.osw_acc_mean), 4), 'granule': r.product_id}
            for r in group.itertuples()
        }
        for site, group in results.groupby('site_id')
    }


def previous_gibs(name: str) -> dict[tuple[str, str], dict]:
    path = BUILD / name / 'catalog.json'
    scenes = json.loads(path.read_text())['scenes'] if path.exists() else {}
    return {
        (site, scene): layers
        for scene, record in scenes.items()
        for site, layers in record['gibs'].items()
        if isinstance(layers, dict) and 'dswx_hls' in layers
    }


def is_current(entry: object) -> bool:
    return isinstance(entry, dict) and entry.get('window_days') == opera.WINDOW_DAYS


def fill_gibs(targets: dict[tuple[str, str], tuple[object, datetime]], known: dict) -> dict[str, dict[str, dict]]:
    cached = {(target, key): known.get(target, {}).get(key) for target in targets for key in GIBS_KEYS}
    todo = [job for job, entry in cached.items() if not is_current(entry)]
    hits = opera.best_dates([(key, bbox(targets[t][0]), targets[t][0].wkt, targets[t][1]) for t, key in todo])
    found = cached | dict(zip(todo, hits))
    by_target = {target: {key: found[(target, key)] for key in GIBS_KEYS} for target in targets}
    scenes = sorted({scene for _, scene in targets})
    return {scene: {site: g for (site, sc), g in by_target.items() if sc == scene} for scene in scenes}


def nisar_water_jobs(name: str, scenes: pd.DataFrame, run_dir: Path | None) -> Jobs:
    folder = BUILD / name / 'nisar-water' / (run_dir.name if run_dir else '')
    return {s.scene: ([s.wtr], folder / f'{s.scene}_WTR.tif') for s in scenes.itertuples() if s.wtr is not None}


def dswx_ni_tiles(data_dir: Path) -> pd.DataFrame:
    paths = sorted((data_dir / 'dswx-ni').rglob('*_B01_WTR.tif'))
    matches = [(DSWX_NI_NAME.fullmatch(p.name), p) for p in paths]
    rows = [m.groupdict() | {'path': p} for m, p in matches if m]
    return pd.DataFrame(rows, columns=['tile', 'acq', 'processed', 'version', 'path'])


def newest_delivery(tiles: pd.DataFrame) -> pd.DataFrame:
    newest = tiles.sort_values('processed').groupby('acq').version.last()
    return tiles[tiles.version == tiles.acq.map(newest)]


def lonlat_bounds(path: Path) -> list[float]:
    info = gdal.Info(str(path), format='json')['wgs84Extent']['coordinates'][0]
    lons, lats = [p[0] for p in info], [p[1] for p in info]
    return [round(min(lons), 4), round(min(lats), 4), round(max(lons), 4), round(max(lats), 4)]


def dswx_ni_tiles_by_scene(scenes: pd.DataFrame, data_dir: Path) -> dict[str, list[dict]]:
    tiles = newest_delivery(dswx_ni_tiles(data_dir))
    scene_of = dict(zip(scenes.acq_key, scenes.scene))
    return {
        scene_of[acq]: [{'name': p.name.removesuffix('_B01_WTR.tif'), 'bbox': lonlat_bounds(p)} for p in group.path]
        for acq, group in tiles.groupby('acq')
        if acq in scene_of
    }


def dswx_ni_jobs(name: str, scenes: pd.DataFrame, data_dir: Path) -> Jobs:
    tiles = newest_delivery(dswx_ni_tiles(data_dir))
    scene_of = dict(zip(scenes.acq_key, scenes.scene))
    groups = [(scene_of[acq], group) for acq, group in tiles.groupby('acq') if acq in scene_of]
    return {
        scene: (list(group.path), BUILD / name / 'dswx-ni' / f'v{group.version.iloc[0]}' / f'{scene}_WTR.tif')
        for scene, group in groups
    }


def run_jobs(name: str, jobs: Jobs, force: bool, options: dict = rasters.CLASS_MAP) -> dict[str, str]:
    rasters.to_web_cogs([job for job in jobs.values() if force or not job[1].exists()], options)
    return {k: dst.relative_to(BUILD / name).as_posix() for k, (_, dst) in jobs.items()}


def scene_record(s: object, gibs: dict, layers: dict[str, dict[str, str]], tiles: dict[str, list]) -> dict:
    return {
        'frame_id': s.frame_id,
        'direction': s.direction,
        'date': s.date,
        'acq_utc': f'{s.acq_dt:%Y-%m-%dT%H:%M:%SZ}',
        'granule_id': s.granule_id,
        **{key: paths.get(s.scene) for key, paths in layers.items()},
        'dswx_ni_tiles': tiles.get(s.scene, []),
        'gibs': {site: {'nisar_gcov': {'date': s.date}} | layers for site, layers in gibs.get(s.scene, {}).items()},
    }


def products(cfg: dict, scenes: pd.DataFrame, run_dir: Path | None, force: bool) -> dict[str, dict[str, str]]:
    name, data = cfg['name'], cfg['data']
    return {
        'nisar_water': run_jobs(name, nisar_water_jobs(name, scenes, run_dir), force),
        'dswx_ni': run_jobs(name, dswx_ni_jobs(name, scenes, data), force),
    }


def build_validation(cfg: dict, run_dir: Path | None, force: bool) -> tuple[dict, gpd.GeoDataFrame]:
    name, tables = cfg['name'], cfg['data'] / 'tables'
    sites = validation_sites(tables)
    granules = sites[['site_id', 'nisar_id']]
    scenes = read_scenes(cfg['data'], run_dir).merge(granules, left_on='granule_id', right_on='nisar_id')
    site_scene = dict(zip(scenes.site_id, scenes.scene))
    times = dict(zip(scenes.scene, scenes.acq_time))
    targets = {
        (s.site_id, site_scene[s.site_id]): (s.geometry, times[site_scene[s.site_id]])
        for s in sites.itertuples()
        if s.site_id in site_scene
    }
    gibs = fill_gibs(targets, {} if force else previous_gibs(name))
    layers = products(cfg, scenes, run_dir, force)
    tiles = dswx_ni_tiles_by_scene(scenes, cfg['data'])
    checks = verification(tables)
    site_records = [
        {
            'id': s.site_id,
            'label': s.label,
            'bbox': bbox(s.geometry),
            'info': {
                'state': text(s.state),
                'country': text(s.country),
                'strata': text(s.strata_label),
                'gcov_quality': text(s.quality),
                'comment': text(s.comments),
                'track': int(s.track),
                'verification': checks.get(s.site_id, {}),
            },
            'scenes': [site_scene[s.site_id]] if s.site_id in site_scene else [],
        }
        for s in sites.itertuples()
    ]
    scene_records = {s.scene: scene_record(s, gibs, layers, tiles) for s in scenes.itertuples()}
    return {'sites': site_records, 'scenes': scene_records}, sites[['site_id', 'label', 'geometry']]


def timeseries_aois(data_dir: Path) -> gpd.GeoDataFrame:
    extra = [gpd.read_parquet(p) for p in sorted((data_dir / 'aois').glob('*.parquet'))]
    frames = [gpd.read_file(data_dir / 'aoi.geojson'), *extra]
    aoi = pd.concat([f.to_crs(4326)[['name', 'state', 'geometry']] for f in frames], ignore_index=True)
    labels = [f'{n}, {s}' for n, s in zip(aoi.name, aoi.state)]
    return gpd.GeoDataFrame(aoi.assign(site_id=[slug(n) for n in aoi.name], label=labels), crs=4326)


def build_timeseries(cfg: dict, run_dir: Path | None, force: bool) -> tuple[dict, gpd.GeoDataFrame]:
    name = cfg['name']
    aoi = timeseries_aois(cfg['data'])
    scenes = read_scenes(cfg['data'], run_dir)
    targets = {(a.site_id, s.scene): (a.geometry, s.acq_time) for a in aoi.itertuples() for s in scenes.itertuples()}
    gibs = fill_gibs(targets, {} if force else previous_gibs(name))
    layers = products(cfg, scenes, run_dir, force)
    tiles = dswx_ni_tiles_by_scene(scenes, cfg['data'])
    frames = dict(zip(scenes.direction, scenes.frame_id))
    site_records = [
        {
            'id': a.site_id,
            'label': a.label,
            'bbox': bbox(a.geometry),
            'info': {'state': text(a.state), 'frames': frames},
            'scenes': scenes.scene.tolist(),
        }
        for a in aoi.itertuples()
    ]
    scene_records = {s.scene: scene_record(s, gibs, layers, tiles) for s in scenes.itertuples()}
    return {'sites': site_records, 'scenes': scene_records}, aoi[['site_id', 'label', 'geometry']]


def folder_counts(scenes: dict, key: str) -> dict[str, int]:
    return dict(Counter(s[key].split('/')[1] for s in scenes.values() if s[key]))


def build_example(name: str, run: str | None = None, force: bool = False) -> dict:
    cfg = example_config(name)
    run_dir = pick_run(cfg['data'], run)
    builder = {'sites': build_validation, 'timeseries': build_timeseries}[cfg['kind']]
    body, footprints = builder(cfg, run_dir, force)
    catalog = {
        'name': name,
        'title': cfg['title'],
        'description': cfg['description'],
        'kind': cfg['kind'],
        'nisar_water_runs': folder_counts(body['scenes'], 'nisar_water'),
        'dswx_ni_versions': folder_counts(body['scenes'], 'dswx_ni'),
        'built': f'{datetime.now().astimezone():%Y-%m-%d %H:%M %Z}',
    } | body
    out = BUILD / name
    out.mkdir(parents=True, exist_ok=True)
    (out / 'catalog.json').write_text(json.dumps(catalog, indent=1, allow_nan=False))
    (out / 'sites.geojson').write_text(footprints.to_crs(4326).to_json(drop_id=True))
    write_index()
    return catalog


def index_html(local: bool = True) -> str:
    data_url = bucket_url() if data_on_s3() and not local else ''
    page = WEB.read_text().replace('__PAGES_URL__', load_config()['site']['pages_url'])
    return page.replace('__DATA_URL__', data_url)


def write_index() -> None:
    BUILD.mkdir(exist_ok=True)
    cfgs = load_config()['examples']
    names = [n for n in cfgs if (BUILD / n / 'catalog.json').exists()]
    examples = [{'name': n} | {k: cfgs[n][k] for k in ('title', 'description', 'kind')} for n in names]
    (BUILD / 'examples.json').write_text(json.dumps(examples, indent=1))
    (BUILD / 'index.html').write_text(index_html())


def summary(catalog: dict) -> dict:
    scenes = catalog['scenes'].values()
    return {
        'sites': len(catalog['sites']),
        'scenes': len(catalog['scenes']),
        'nisar_water': catalog['nisar_water_runs'],
        'dswx_ni': catalog['dswx_ni_versions'],
        **{k: sum(bool((g.get(k) or {}).get('date')) for s in scenes for g in s['gibs'].values()) for k in GIBS_KEYS},
    }
