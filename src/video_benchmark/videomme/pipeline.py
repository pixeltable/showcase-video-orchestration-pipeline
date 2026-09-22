"""Video-MME Pixeltable catalog: TableModel apply + video_id-scoped queries."""

from __future__ import annotations

import pixeltable as pxt

from video_benchmark.config import BenchmarkConfig
from video_benchmark.schema import model_column_names
from video_benchmark.videomme.schema import (
    CATALOG_DIR,
    build_core_models,
    build_oss_keyframe_models,
    build_oss_parent_models,
    build_parent_models,
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
_OSS_PARENT_COLS = (
    'oss_shared_context',
    'oss_frame_context_compact',
    'oss_frame_context_summarized',
    'oss_frame_context_selected',
    'oss_frame_context_deduped',
    'oss_frame_context',
)


def rollup_exceeds_child_count(rollup, child_count: int) -> bool:
    return isinstance(rollup, list) and len(rollup) > int(child_count)


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

    if 'oss_frame_insight' in set(keyframes.columns()):

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
    else:
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
    for col in (*_OSS_PARENT_COLS, *_GEMINI_PARENT_COLS):
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
    """True if any parent rollup has more frames than that video's keyframes."""
    del max_frames_per_video  # kept for runner call-site compatibility
    load_pipeline()
    assert videos is not None
    if videos.count() == 0 or keyframes is None:
        return False
    if 'gemini_frame_context' not in set(videos.columns()):
        return False
    kf_df = keyframes.select(keyframes.video_id).collect().to_pandas()
    counts = kf_df.groupby('video_id').size().to_dict() if not kf_df.empty else {}
    rows = videos.select(videos.video_id, videos.gemini_frame_context).collect()
    for row in rows:
        vid = row.get('video_id')
        child_n = int(counts.get(vid, 0))
        if rollup_exceeds_child_count(row.get('gemini_frame_context') or [], child_n):
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
    frame_col = 'oss_frame_context' if 'oss_frame_context' in set(videos.columns()) else None
    cols = [videos.video_id, videos.oss_shared_context]
    if frame_col:
        cols.append(videos.oss_frame_context)
    rows = videos.select(*cols).collect()
    for row in rows:
        text = str(row.get('oss_shared_context') or '').strip()
        if not text:
            return False
        if frame_col:
            ctx = row.get('oss_frame_context') or []
            if not isinstance(ctx, list) or not ctx:
                return False
    return True


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
    elif not oss_shared_ready():
        _recompute_oss_parent()


def _recompute_oss_parent() -> None:
    """Fill OSS rollups that exist but are empty. Column presence is not readiness."""
    assert videos is not None
    for col in (
        'oss_frame_context',
        'oss_frame_context_deduped',
        'oss_frame_context_selected',
        'oss_frame_context_summarized',
        'oss_frame_context_compact',
        'oss_shared_context',
    ):
        if col not in set(videos.columns()):
            continue
        status = videos.recompute_columns(col, cascade=False)
        if status.num_excs:
            print(f'Recompute ({col}): {status.insert_msg()}', flush=True)


__all__ = [
    'audio_chunks',
    'ensure_oss_shared',
    'keyframes',
    'load_pipeline',
    'model_column_names',
    'oss_shared_ready',
    'parent_context_is_cross_contaminated',
    'rollup_exceeds_child_count',
    'rebuild_parent_context',
    'reset_catalog',
    'setup_pipeline',
    'videos',
]
