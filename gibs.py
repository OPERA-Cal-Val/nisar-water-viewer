import math
import time
from functools import cache
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from uuid import uuid4

import geopandas as gpd
import numpy as np
import shapely
from osgeo import gdal


gdal.UseExceptions()

GIBS = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best'
HALF = 20037508.342789244
TILE = 256
LAYERS = {
    'dswx_hls': ('OPERA_L3_Dynamic_Surface_Water_Extent-HLS', 12, (3,)),
    'dswx_s1': ('OPERA_L3_Dynamic_Surface_Water_Extent-Sentinel-1', 12, (3,)),
    'rtc_s1': ('OPERA_L2_Radiometric_Terrain_Corrected_SAR_Sentinel-1', 12, (3, 6)),
}
CLOUD = (175, 175, 175)
CHANNELS = {1: [0, 0, 0], 2: [0, 0, 0, 1], 3: [0, 1, 2], 4: [0, 1, 2, 3]}


def tile_xy(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2**z
    lat = max(min(lat, 85.0), -85.0)
    return int((lon + 180) / 360 * n), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)


def tile_range(bounds: tuple[float, ...], z: int) -> list[tuple[int, int]]:
    x0, y0 = tile_xy(bounds[0], bounds[3], z)
    x1, y1 = tile_xy(bounds[2], bounds[1], z)
    return [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]


def pick_zoom(bounds: tuple[float, ...], max_tiles: int = 9) -> int:
    return next((z for z in range(10, 5, -1) if len(tile_range(bounds, z)) <= max_tiles), 6)


def fetch_png(url: str, png_types: tuple[int, ...], attempts: int = 4) -> bytes | None:
    for attempt in range(attempts):
        try:
            with urlopen(url, timeout=60) as response:
                data = response.read()
            if data[25] in png_types:
                return data
        except HTTPError as error:
            if error.code in (400, 404):
                return None
        except (URLError, TimeoutError):
            pass
        time.sleep(attempt)
    return None


def png_rgba(data: bytes) -> np.ndarray:
    name = f'/vsimem/{uuid4().hex}.png'
    gdal.FileFromMemBuffer(name, data)
    dataset = gdal.Open(name)
    band = dataset.GetRasterBand(1)
    table = band.GetColorTable()
    pixels = dataset.ReadAsArray()
    lut = np.array([table.GetColorEntry(i) for i in range(table.GetCount())] if table else [], dtype='uint8')
    dataset = None
    gdal.Unlink(name)
    if table:
        return np.vstack([lut, np.zeros((256 - len(lut), 4), 'uint8')])[pixels]
    stack = pixels if pixels.ndim == 3 else pixels[None]
    rgba = np.moveaxis(stack[CHANNELS[len(stack)]], 0, -1)
    return rgba if rgba.shape[-1] == 4 else np.concatenate([rgba, np.full((*rgba.shape[:2], 1), 255, 'uint8')], -1)


def tile_url(key: str, date: str, z: int, x: int, y: int) -> str:
    layer, level, _ = LAYERS[key]
    return f'{GIBS}/{layer}/default/{date}/GoogleMapsCompatible_Level{level}/{z}/{y}/{x}.png'


def pixel_centres(z: int, x: int, y: int) -> tuple[np.ndarray, np.ndarray]:
    res = 2 * HALF / (TILE * 2**z)
    offsets = (np.arange(TILE) + 0.5) * res
    return np.meshgrid(-HALF + x * TILE * res + offsets, HALF - y * TILE * res - offsets)


def valid_pixels(key: str, rgba: np.ndarray) -> np.ndarray:
    seen = rgba[..., 3] > 0
    return seen & ~np.all(rgba[..., :3] == CLOUD, axis=-1) if key == 'dswx_hls' else seen


def tile_counts(key: str, date: str, region: object, z: int, x: int, y: int) -> tuple[int, int]:
    xs, ys = pixel_centres(z, x, y)
    mask = shapely.contains_xy(region, xs, ys)
    if not mask.any():
        return 0, 0
    data = fetch_png(tile_url(key, date, z, x, y), LAYERS[key][2])
    return int(mask.sum()), int((mask & valid_pixels(key, png_rgba(data))).sum()) if data else 0


@cache
def coverage(key: str, date: str, polygon_wkt: str) -> float:
    polygon = gpd.GeoSeries.from_wkt([polygon_wkt], crs=4326)
    region = polygon.to_crs(3857).iloc[0]
    bounds = polygon.total_bounds
    z = pick_zoom(bounds)
    counts = [tile_counts(key, date, region, z, x, y) for x, y in tile_range(bounds, z)]
    inside = sum(c[0] for c in counts)
    return round(sum(c[1] for c in counts) / inside, 3) if inside else 0.0
