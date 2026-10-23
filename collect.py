import filecmp
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import rasters


Pairs = list[tuple[Path, Path]]
MANIFESTS = ('scenes.parquet', 'scenes.csv', 'aoi.geojson')


def link_file(src: Path, dst: Path) -> str:
    target = src.resolve()
    if dst.is_symlink():
        return 'kept' if dst.resolve() == target else 'conflict'
    if dst.exists() and not filecmp.cmp(dst, target, shallow=False):
        return 'conflict'
    if dst.exists():
        dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.symlink_to(target)
    return 'linked'


def link_pairs(pairs: Pairs, max_workers: int = 8) -> dict[str, int]:
    with ThreadPoolExecutor(max_workers) as pool:
        outcomes = list(pool.map(lambda pair: link_file(*pair), pairs))
    conflicts = [str(dst) for (_, dst), outcome in zip(pairs, outcomes) if outcome == 'conflict']
    if conflicts:
        print('left alone (already points somewhere else or differs):', *conflicts, sep='\n  ')
    return dict(Counter(outcomes))


def nisar_water_pairs(example_dir: Path, dest: Path) -> Pairs:
    manifests = [example_dir / name for name in MANIFESTS if (example_dir / name).exists()]
    frames = sorted(example_dir.glob('out/*/frame/ni-water_*_WTR.tif'))
    runs = [dest / 'nisar-water' / rasters.run_label(f) / f.name for f in frames]
    return [(m, dest / m.name) for m in manifests] + list(zip(frames, runs))


def dswx_ni_pairs(source: Path, dest: Path) -> Pairs:
    wtrs = sorted(source.rglob('OPERA_L3_DSWx-NI_*_B01_WTR.tif'))
    return [(w, dest / 'dswx-ni' / w.relative_to(source)) for w in wtrs]


def table_pairs(tables: list[Path], dest: Path) -> Pairs:
    return [(t, dest / 'tables' / t.name) for t in tables]


def collect_example(sources: dict, dest: Path) -> dict[str, dict[str, int]]:
    groups = {
        'nisar-water': nisar_water_pairs(sources['nisar_water'], dest) if 'nisar_water' in sources else [],
        'dswx-ni': dswx_ni_pairs(sources['dswx_ni'], dest) if 'dswx_ni' in sources else [],
        'tables': table_pairs(sources.get('tables', []), dest),
        'aois': [(p, dest / 'aois' / p.name) for p in sources.get('aois', [])],
    }
    return {group: link_pairs(pairs) for group, pairs in groups.items() if pairs}
