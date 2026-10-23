import io
import subprocess
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import click

import catalog
import collect
import pages


class RangeHandler(SimpleHTTPRequestHandler):
    def send_head(self) -> object:
        if self.path.split('?')[0].split('#')[0] in ('/', '/index.html'):
            return self.send_page(catalog.index_html().encode())
        span = self.headers.get('Range', '')
        path = Path(self.translate_path(self.path))
        if not span.startswith('bytes=') or not path.is_file():
            return super().send_head()
        size = path.stat().st_size
        first, _, last = span[6:].split(',')[0].partition('-')
        start = int(first) if first else max(size - int(last), 0)
        end = min(int(last), size - 1) if first and last else size - 1
        handle = path.open('rb')
        handle.seek(start)
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(str(path)))
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        self.end_headers()
        self.range_left = end - start + 1
        return handle

    def send_page(self, body: bytes) -> io.BytesIO:
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        return io.BytesIO(body)

    def copyfile(self, source: object, outputfile: object) -> None:
        left = getattr(self, 'range_left', None)
        if left is None:
            return super().copyfile(source, outputfile)
        outputfile.write(source.read(left))
        self.range_left = None
        return None

    def end_headers(self) -> None:
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Expose-Headers', 'Content-Range, Content-Length, Accept-Ranges')
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


def bucket() -> dict:
    return catalog.load_config()['bucket']


def aws(*args: str) -> None:
    click.echo('aws ' + ' '.join(args))
    subprocess.run(['aws', *args], check=True)


@click.group()
def cli() -> None:
    pass


def example_names(names: tuple[str, ...]) -> tuple[str, ...]:
    return names or tuple(catalog.load_config()['examples'])


@cli.command('collect')
@click.argument('names', nargs=-1)
def collect_sources(names: tuple[str, ...]) -> None:
    for name in example_names(names):
        cfg = catalog.example_config(name)
        click.echo(f'{name}: {collect.collect_example(cfg["sources"], cfg["data"])}')


@cli.command()
@click.argument('names', nargs=-1)
@click.option('--run', default=None, help='nisar-water run folder under data/<example>/nisar-water/ (default: newest).')
@click.option('--force', is_flag=True, help='Rewrite every COG and redo every OPERA date lookup.')
def build(names: tuple[str, ...], run: str | None, force: bool) -> None:
    for name in example_names(names):
        click.echo(f'{name}: {catalog.summary(catalog.build_example(name, run, force))}')


@cli.command()
@click.option('--port', default=8000, show_default=True)
def serve(port: int) -> None:
    catalog.write_index()
    handler = partial(RangeHandler, directory=str(catalog.BUILD))
    click.echo(f'http://localhost:{port}/')
    ThreadingHTTPServer(('', port), handler).serve_forever()


@cli.command('site')
def assemble_site() -> None:
    click.echo(f'{pages.SITE}: {pages.assemble()}')


@cli.command()
@click.option('--dryrun', is_flag=True)
def upload(dryrun: bool) -> None:
    catalog.write_index()
    sync = ['s3', 'sync', str(catalog.BUILD), f's3://{bucket()["name"]}/', *(['--dryrun'] if dryrun else [])]
    aws(*sync, *'--exclude * --include *.tif --content-type image/tiff'.split(), '--cache-control', 'max-age=86400')
    aws(*sync, *'--exclude *.tif --exclude *.aux.xml --exclude index.html'.split(), '--cache-control', 'no-cache')


if __name__ == '__main__':
    cli()
