"""Video-MME Pixeltable catalog: TableModel apply + video_id-scoped queries."""

from __future__ import annotations

import pixeltable as pxt

from video_benchmark.config import BenchmarkConfig
from video_benchmark.videomme.schema import (
    CATALOG_DIR,
    build_core_models,
    build_oss_keyframe_models,
    build_oss_parent_models,
    build_parent_models,
    model_column_names,
)

videos: pxt.Table | None = None
keyframes: pxt.Table | None = None
audio_chunks: pxt.Table | None = None

_gemini_frame_insights = None
_gemini_audio_transcripts = None
_oss_frame_insights = None

_GEMINI_PARENT_COLS = (
    'gemini_asr_cost',
    'gemini_vision_track_cost',
    'shared_context',
    'gemini_frame_context_summarized',
    'gemini_frame_context_selected',
    'gemini_frame_context_deduped',
    'gemini_transcript_context',
    'gemini_frame_context',
)


def reset_catalog() -> None:
    global videos, keyframes, audio_chunks
    global _gemini_frame_insights, _gemini_audio_transcripts, _oss_frame_insights
    pxt.drop_dir(CATALOG_DIR, force=True, if_not_exists='ignore')
    videos = None
    keyframes = None
    audio_chunks = None
    _gemini_frame_insights = None
    _gemini_audio_transcripts = None
    _oss_frame_insights = None


def _bind_tables() -> None:
    global videos, keyframes, audio_chunks
    videos = pxt.get_table(f'{CATALOG_DIR}.videos', if_not_exists='ignore')
    keyframes = pxt.get_table(f'{CATALOG_DIR}.keyframes', if_not_exists='ignore')
    audio_chunks = pxt.get_table(f'{CATALOG_DIR}.audio_chunks', if_not_exists='ignore')


def _register_scoped_queries() -> None:
    """Bind video_id-scoped rollup queries. Unscoped queries bleed across videos."""
    global _gemini_frame_insights, _gemini_audio_transcripts, _oss_frame_insights
    if keyframes is None or audio_chunks is None:
        raise RuntimeError('Video-MME views are not loaded.')

    @pxt.query
    def gemini_frame_insights(video_id: str):
        return (
            keyframes.where(keyframes.video_id == video_id)
            .order_by(keyframes.global_position_ms)
            .select(
                pos_msec=keyframes.global_position_ms,
                segment_start=keyframes.segment_start,
                frame_insight=keyframes.gemini_frame_insight,
                frame_cost=keyframes.gemini_frame_cost,
            )
        )

    @pxt.query
    def gemini_audio_transcripts(video_id: str):
        return (
            audio_chunks.where(audio_chunks.video_id == video_id)
            .order_by(audio_chunks.segment_start)
            .select(
                segment_lines=audio_chunks.gemini_transcript_lines,
            )
        )

    _gemini_frame_insights = gemini_frame_insights
    _gemini_audio_transcripts = gemini_audio_transcripts

    try:
        _ = keyframes.oss_frame_insight

        @pxt.query
        def oss_frame_insights(video_id: str):
            return (
                keyframes.where(keyframes.video_id == video_id)
                .order_by(keyframes.global_position_ms)
                .select(
                    pos_msec=keyframes.global_position_ms,
                    segment_start=keyframes.segment_start,
                    frame_insight=keyframes.oss_frame_insight,
                )
            )

        _oss_frame_insights = oss_frame_insights
    except Exception:  # noqa: BLE001
        _oss_frame_insights = None


def load_pipeline() -> None:
    pxt.create_dir(CATALOG_DIR, if_exists='ignore')
    _bind_tables()
    if videos is None or keyframes is None or audio_chunks is None:
        raise RuntimeError('Video-MME tables are not initialized.')
    _register_scoped_queries()


def setup_pipeline(config: BenchmarkConfig, *, reset: bool = False) -> None:
    if reset:
        reset_catalog()
    pxt.create_dir(CATALOG_DIR, if_exists='ignore')
    existing = pxt.get_table(f'{CATALOG_DIR}.videos', if_not_exists='ignore')
    existing_cols = set(existing.columns()) if existing is not None else set()
    if 'shared_context' not in existing_cols:
        build_core_models(config).update_all(CATALOG_DIR)
    _bind_tables()
    _register_scoped_queries()
    build_parent_models(
        config,
        frame_insights=_gemini_frame_insights,
        audio_transcripts=_gemini_audio_transcripts,
    ).update_all(CATALOG_DIR)
    _bind_tables()


def rebuild_parent_context(config: BenchmarkConfig) -> None:
    """Drop and recreate parent rollups only (keeps keyframes/ASR; fixes cross-video bleed)."""
    load_pipeline()
    assert videos is not None
    for col in _GEMINI_PARENT_COLS:
        try:
            videos.drop_column(col)
            print(f'Dropped videomme.videos.{col}', flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f'Skip drop {col}: {exc}', flush=True)
    _bind_tables()
    _register_scoped_queries()
    has_oss = keyframes is not None and 'oss_frame_insight' in set(keyframes.columns())
    if has_oss and _oss_frame_insights is not None:
        build_oss_parent_models(
            config,
            frame_insights=_gemini_frame_insights,
            audio_transcripts=_gemini_audio_transcripts,
            oss_frame_insights=_oss_frame_insights,
        ).update_all(CATALOG_DIR)
    else:
        build_parent_models(
            config,
            frame_insights=_gemini_frame_insights,
            audio_transcripts=_gemini_audio_transcripts,
        ).update_all(CATALOG_DIR)
    _bind_tables()
    print('Rebuilt parent context columns (video_id-scoped).', flush=True)


def parent_context_is_cross_contaminated(max_frames_per_video: int = 24) -> bool:
    """True if any parent rollup includes frames from other videos."""
    load_pipeline()
    assert videos is not None
    if videos.count() == 0:
        return False
    if 'gemini_frame_context' not in set(videos.columns()):
        return False
    rows = videos.select(videos.video_id, videos.gemini_frame_context).collect()
    for row in rows:
        ctx = row.get('gemini_frame_context') or []
        if isinstance(ctx, list) and len(ctx) > max_frames_per_video * 2:
            return True
    return False


def oss_shared_ready() -> bool:
    """True if oss_shared_context exists and is populated for all videos."""
    load_pipeline()
    assert videos is not None
    if 'oss_shared_context' not in set(videos.columns()):
        return False
    if videos.count() == 0:
        return False
    df = videos.select(videos.video_id, videos.oss_shared_context).collect().to_pandas()
    texts = df['oss_shared_context'].astype(str)
    return not (df['oss_shared_context'].isna().any() or (texts.str.len() < 20).any())


def ensure_oss_shared(config: BenchmarkConfig) -> None:
    if videos is None or keyframes is None:
        load_pipeline()
    assert videos is not None and keyframes is not None
    if 'oss_frame_insight' not in set(keyframes.columns()):
        build_oss_keyframe_models(
            config,
            frame_insights=_gemini_frame_insights,
            audio_transcripts=_gemini_audio_transcripts,
        ).update_all(CATALOG_DIR)
        _bind_tables()
        _register_scoped_queries()
    if 'oss_shared_context' not in set(videos.columns()):
        if _oss_frame_insights is None:
            raise RuntimeError('OSS frame query is not registered.')
        build_oss_parent_models(
            config,
            frame_insights=_gemini_frame_insights,
            audio_transcripts=_gemini_audio_transcripts,
            oss_frame_insights=_oss_frame_insights,
        ).update_all(CATALOG_DIR)
        _bind_tables()


__all__ = [
    'audio_chunks',
    'ensure_oss_shared',
    'keyframes',
    'load_pipeline',
    'model_column_names',
    'oss_shared_ready',
    'parent_context_is_cross_contaminated',
    'rebuild_parent_context',
    'reset_catalog',
    'setup_pipeline',
    'videos',
]
