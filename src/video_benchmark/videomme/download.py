"""Download Video-MME YouTube clips with yt-dlp; soft-skip failures."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from video_benchmark.videomme import VIDEOME_ASSETS

# Cap resolution/size so long Video-MME clips stay runnable/affordable.
MAX_HEIGHT = 480
MAX_FILESIZE = '200M'
DOWNLOAD_TIMEOUT_SEC = 240


def video_file_path(video_id: str, assets_dir: Path | None = None) -> Path:
    root = assets_dir or VIDEOME_ASSETS
    return root / 'videos' / f'{video_id}.mp4'


def download_video(
    *,
    video_id: str,
    url: str,
    assets_dir: Path | None = None,
    timeout_sec: int = DOWNLOAD_TIMEOUT_SEC,
) -> Path | None:
    """
    Download a single YouTube URL to assets/videomme/videos/<video_id>.mp4.
    Returns path on success, None on failure (soft-skip).
    """
    out = video_file_path(video_id, assets_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 0:
        return out

    yt_dlp = shutil.which('yt-dlp')
    if not yt_dlp:
        try:
            import yt_dlp  # noqa: F401

            cmd = [__import__('sys').executable, '-m', 'yt_dlp']
        except ImportError:
            raise RuntimeError(
                'yt-dlp not found. Install with: pip install -e ".[videomme]"'
            ) from None
    else:
        cmd = [yt_dlp]

    # Prefer <=480p mp4; hard-cap filesize for long clips.
    tmp_tmpl = str(out.with_suffix('')) + '.%(ext)s'
    fmt = (
        f'bv*[height<={MAX_HEIGHT}][ext=mp4]+ba[ext=m4a]/'
        f'b[height<={MAX_HEIGHT}][ext=mp4]/w'
    )
    full_cmd = [
        *cmd,
        '--no-playlist',
        '--max-filesize',
        MAX_FILESIZE,
        '-f',
        fmt,
        '--merge-output-format',
        'mp4',
        '-o',
        tmp_tmpl,
        '--',
        url,
    ]
    try:
        proc = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    if out.exists() and out.stat().st_size > 0:
        return out
    matches = list(out.parent.glob(f'{video_id}.*'))
    for m in matches:
        if m.suffix.lower() in {'.mp4', '.mkv', '.webm'} and m.stat().st_size > 0:
            if m != out:
                m.replace(out)
            return out if out.exists() else None
    return None


def download_videos(
    videos: list[dict[str, str]],
    *,
    assets_dir: Path | None = None,
) -> dict[str, str]:
    """
    Download all videos; return map video_id -> local path for successes only.
    """
    downloads: dict[str, str] = {}
    for v in videos:
        vid = v['video_id']
        print(f'  downloading {vid} ...', flush=True)
        path = download_video(video_id=vid, url=v['url'], assets_dir=assets_dir)
        if path is not None:
            downloads[vid] = str(path.resolve())
            print(f'  downloaded {vid} -> {path.name}', flush=True)
        else:
            print(f'  skip {vid} (download failed / oversize)', flush=True)
    return downloads
