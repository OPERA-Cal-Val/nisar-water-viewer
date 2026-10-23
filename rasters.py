from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from osgeo import gdal


gdal.UseExceptions()

NODATA = 255
CLASS_MAP = {'resampling': 'near', 'overviews': 'MODE', 'nodata': NODATA}


def cog_options(overviews: str, resampling: str) -> list[str]:
    return [
        'TILING_SCHEME=GoogleMapsCompatible',
        'ZOOM_LEVEL_STRATEGY=UPPER',
        f'RESAMPLING={resampling.upper()}',
        f'OVERVIEW_RESAMPLING={overviews}',
        'COMPRESS=DEFLATE',
    ]


def to_web_cog(
    sources: list[Path], dst: Path, resampling: str = 'near', overviews: str = 'MODE', nodata: int = NODATA
) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix('.tmp.tif')
    gdal.Warp(
        str(tmp),
        [str(s) for s in sources],
        format='COG',
        dstSRS='EPSG:3857',
        resampleAlg=resampling,
        srcNodata=nodata,
        dstNodata=nodata,
        creationOptions=cog_options(overviews, resampling),
    )
    tmp.replace(dst)
    return dst


def to_web_cogs(jobs: list[tuple[list[Path], Path]], options: dict = CLASS_MAP, max_workers: int = 4) -> list[Path]:
    with ThreadPoolExecutor(max_workers) as pool:
        return list(pool.map(lambda job: to_web_cog(*job, **options), jobs))


def tags(path: Path) -> dict[str, str]:
    return gdal.Open(str(path)).GetMetadata()


def is_release(version: str) -> bool:
    return bool(version) and '+' not in version and 'dev' not in version


def run_label(path: Path) -> str:
    product = tags(path)
    version = product.get('software_version', '')
    if is_release(version):
        return f'v{version}'
    return f'dev-{product["git_sha"]}' if product.get('git_sha') else 'unversioned'
