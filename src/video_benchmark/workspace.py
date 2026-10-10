"""Loopback-only interactive view of the same provider-free Pixeltable media graph."""

import argparse
import os
import shutil
import socket
import subprocess
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

from video_benchmark.local_demo import make_demo_video


def create_app(graph, home: Path, *, origin: str):
    """Serve only generated media and bounded policy/refresh operations on this graph."""
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

    app = FastAPI(title='Pixeltable evidence workspace', docs_url=None, redoc_url=None)
    lock = threading.RLock()
    host = urlsplit(origin).netloc
    media = {'clip': graph.source}
    frames = graph.frames
    for index, row in enumerate(
        frames.order_by(frames.position_sec).select(frames.thumbnail).collect()
    ):
        path = home / f'frame-{index}.png'
        row['thumbnail'].save(path)
        media[f'frame-{index}'] = path
    clips = graph.clips
    media['audio'] = Path(next(iter(clips.select(path=clips.audio.localpath).collect()))['path'])

    @app.middleware('http')
    async def local_boundary(request: Request, call_next):
        if request.headers.get('host') != host:
            return JSONResponse(
                {'detail': 'Use the local workspace URL printed at launch.'}, status_code=403
            )
        if request.method != 'GET':
            if request.headers.get('origin') != origin:
                return JSONResponse(
                    {'detail': 'Workspace writes require its local origin.'}, status_code=403
                )
            if request.headers.get('content-type', '').split(';')[0] != 'application/json':
                return JSONResponse(
                    {'detail': 'Send a JSON policy or refresh request.'}, status_code=415
                )
            try:
                length = int(request.headers.get('content-length', '1025'))
            except ValueError:
                length = 1025
            if not 0 <= length <= 1024:
                return JSONResponse(
                    {'detail': 'Send a JSON request of at most 1024 bytes.'}, status_code=413
                )
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self'; media-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )
        return response

    @app.get('/', response_class=HTMLResponse)
    def index():
        return (Path(__file__).parent / 'web' / 'workspace.html').read_text()

    @app.get('/api/state')
    def state():
        with lock:
            return graph.state()

    @app.get('/media/{media_id}')
    def preview(media_id: str):
        if media_id not in media:
            raise HTTPException(404, 'This media is not part of the generated graph.')
        return FileResponse(media[media_id])

    # Parse bounded JSON explicitly so NaN, booleans, unknown fields, and IDs are rejected.
    @app.post('/api/policy')
    async def policy(request: Request):
        try:
            payload = await request.json()
            if not isinstance(payload, dict) or set(payload) != {'minimum_brightness'}:
                raise ValueError('Send only minimum_brightness.')
            value = payload['minimum_brightness']
            if type(value) not in {int, float}:
                raise ValueError('Brightness must be a number between 0 and 255.')
            # Pixeltable runs in a worker thread, rather than blocking the HTTP event loop.
            from starlette.concurrency import run_in_threadpool

            def update():
                with lock:
                    graph.change_policy(value)
                    return graph.state()

            return await run_in_threadpool(update)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post('/api/refresh')
    async def refresh(request: Request):
        try:
            payload = await request.json()
            if not isinstance(payload, dict) or set(payload) != {'request_id'}:
                raise ValueError('Send only request_id.')
            if payload['request_id'] not in {'first', 'second'}:
                raise ValueError('Choose the first or second request.')
            from starlette.concurrency import run_in_threadpool

            def update():
                with lock:
                    graph.refresh(payload['request_id'])
                    return graph.state()

            return await run_in_threadpool(update)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc

    class BoundedRequestBody:
        """Bound actual received bytes even when Content-Length is inaccurate."""

        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope['type'] != 'http' or scope['method'] == 'GET':
                return await self.app(scope, receive, send)
            body = bytearray()
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                chunk = message.get('body', b'')
                if len(body) + len(chunk) > 1024:
                    response = JSONResponse(
                        {'detail': 'The request is too large.'}, status_code=413
                    )
                    return await response(scope, receive, send)
                body.extend(chunk)
                if not message.get('more_body', False):
                    break
            replayed = False

            async def replay():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                return await receive()

            await self.app(scope, replay, send)

    app.add_middleware(BoundedRequestBody)
    return app


def main() -> int:
    parser = argparse.ArgumentParser(description='Open the zero-key local evidence workspace.')
    parser.add_argument('--port', type=int, default=0, help='Loopback port; default is assigned')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('--port must be between 0 and 65535')
    try:
        import uvicorn
    except ImportError:
        parser.error('Install the workspace extra: pip install -e ".[workspace]"')
    home = Path(tempfile.mkdtemp(prefix='pxt-evidence-workspace-'))
    os.environ['PIXELTABLE_HOME'] = str(home)
    os.environ['PIXELTABLE_PGDATA'] = str(home / 'pgdata')
    os.environ.pop('PIXELTABLE_DB_CONNECT_STR', None)
    # Own the listening socket before printing an assigned port; no port-selection race.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', args.port))
        listener.listen(128)
        port = listener.getsockname()[1]
        os.environ['PXT_PORT'] = str(port)
        try:
            from video_benchmark.local_graph import LocalMediaGraph

            graph = LocalMediaGraph(make_demo_video(home / 'demo.mp4'))
            origin = f'http://127.0.0.1:{port}'
            app = create_app(graph, home, origin=origin)
            print(f'Evidence workspace: {origin}\nTemporary catalog: {home}', flush=True)
            try:
                uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port)).run(
                    sockets=[listener]
                )
            except KeyboardInterrupt:
                pass
        finally:
            if (home / 'pgdata').exists():
                from pixeltable_pgserver import pg_ctl

                try:
                    pg_ctl(['-m', 'fast', '-w', 'stop'], pgdata=home / 'pgdata')
                except subprocess.CalledProcessError:
                    pass
            if (home / 'pgdata' / 'postmaster.pid').exists():
                print(
                    f'Catalog preserved at {home}: database shutdown did not complete.', flush=True
                )
            else:
                shutil.rmtree(home, ignore_errors=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
