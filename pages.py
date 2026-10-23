import json
import os
import shutil

import catalog


SITE = catalog.ROOT / 'site'
PAGES_LIMIT_MB = 1000
LAYER_KEYS = ('nisar_water', 'dswx_ni')


def example_files(name: str) -> list[str]:
    scenes = json.loads((catalog.BUILD / name / 'catalog.json').read_text())['scenes'].values()
    rasters = sorted({s[k] for s in scenes for k in LAYER_KEYS if s.get(k)})
    return [f'{name}/{path}' for path in ['catalog.json', 'sites.geojson', *rasters]]


def site_files() -> list[str]:
    names = [e['name'] for e in json.loads((catalog.BUILD / 'examples.json').read_text())]
    return ['examples.json', *[f for name in names for f in example_files(name)]]


def place(relative: str) -> int:
    src, dst = catalog.BUILD / relative, SITE / relative
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.link(src, dst) if src.suffix == '.tif' else shutil.copy2(src, dst)
    return dst.stat().st_size


def clear_site() -> None:
    stale = [p for p in SITE.rglob('*') if p.is_file() and '.git' not in p.relative_to(SITE).parts]
    for path in stale:
        path.unlink()


def assemble() -> dict:
    catalog.write_index()
    SITE.mkdir(exist_ok=True)
    clear_site()
    sizes = [] if catalog.data_on_s3() else [place(relative) for relative in site_files()]
    (SITE / 'index.html').write_text(catalog.index_html(local=False))
    (SITE / '.nojekyll').touch()
    return {'files': len(sizes), 'megabytes': round(sum(sizes) / 1e6, 1), 'pages_limit_megabytes': PAGES_LIMIT_MB}
