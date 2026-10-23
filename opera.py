import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from itertools import groupby
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import gibs


CMR = 'https://cmr.earthdata.nasa.gov/search/granules.json'
SHORT_NAMES = {
    'dswx_hls': 'OPERA_L3_DSWX-HLS_V1',
    'dswx_s1': 'OPERA_L3_DSWX-S1_V1',
    'rtc_s1': 'OPERA_L2_RTC-S1_V1',
}
WINDOW_DAYS = 7
MIN_COVERAGE = 0.9


def read_json(url: str, attempts: int = 5) -> dict:
    for attempt in range(attempts):
        try:
            with urlopen(url, timeout=120) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
            time.sleep(2**attempt)
    return {}


def search_granules(short_name: str, bbox: list[float], start: datetime, end: datetime) -> list[dict]:
    params = urlencode(
        {
            'short_name': short_name,
            'bounding_box': ','.join(f'{v:.5f}' for v in bbox),
            'temporal': f'{start:%Y-%m-%dT%H:%M:%SZ},{end:%Y-%m-%dT%H:%M:%SZ}',
            'page_size': 2000,
        }
    )
    return read_json(f'{CMR}?{params}')['feed']['entry']


def entry_bbox(entry: dict) -> list[float] | None:
    rings = [p[0] for p in entry.get('polygons', [])] + entry.get('boxes', [])
    values = [float(v) for ring in rings for v in ring.split()]
    lats, lons = values[0::2], values[1::2]
    return [round(min(lons), 4), round(min(lats), 4), round(max(lons), 4), round(max(lats), 4)] if values else None


def acquired(entry: dict) -> datetime:
    return datetime.fromisoformat(entry['time_start'])


def date_candidates(short_name: str, bbox: list[float], t: datetime, days: int = WINDOW_DAYS) -> list[dict]:
    window = timedelta(days=days)
    entries = search_granules(short_name, bbox, t - window, t + window)
    dated = sorted(((f'{acquired(e):%Y-%m-%d}', e) for e in entries), key=lambda d: (d[0], d[1]['title']))
    groups = {date: [e for _, e in items] for date, items in groupby(dated, key=lambda d: d[0])}
    return [
        {
            'date': date,
            'days': min((round((acquired(e) - t).total_seconds() / 86400, 2) for e in group), key=abs),
            'granules': [{'name': e['title'], 'bbox': entry_bbox(e)} for e in group],
            'collection': group[0]['collection_concept_id'],
        }
        for date, group in groups.items()
    ]


def choose(candidates: list[dict]) -> dict:
    covered = [c for c in candidates if c['coverage'] >= MIN_COVERAGE]
    if covered:
        return min(covered, key=lambda c: abs(c['days']))
    best = max(candidates, key=lambda c: (c['coverage'], -abs(c['days'])), default=None)
    return best if best and best['coverage'] > 0 else {'date': None, 'coverage': 0.0}


def best_dates(queries: list[tuple[str, list[float], str, datetime]], max_workers: int = 16) -> list[dict]:
    with ThreadPoolExecutor(max_workers) as pool:
        candidates = list(pool.map(lambda q: date_candidates(SHORT_NAMES[q[0]], q[1], q[3]), queries))
        jobs = sorted({(q[0], c['date'], q[2]) for q, cs in zip(queries, candidates) for c in cs})
        scores = dict(zip(jobs, pool.map(lambda job: gibs.coverage(*job), jobs)))
    scored = [[c | {'coverage': scores[(q[0], c['date'], q[2])]} for c in cs] for q, cs in zip(queries, candidates)]
    return [choose(cs) | {'window_days': WINDOW_DAYS} for cs in scored]
