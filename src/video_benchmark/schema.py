"""Pursuit catalog as path-gated TableModel classes (Pixeltable 0.7+)."""

# TableModel class bodies bind iterator/base columns that ruff cannot see.
# ruff: noqa: F821

from __future__ import annotations

from dataclasses import dataclass

import pixeltable as pxt
from pixeltable.functions.audio import audio_splitter
from pixeltable.functions.gemini import generate_content
from pixeltable.functions.gemini import transcribe as gemini_transcribe
from pixeltable.functions.video import (
    extract_audio,
    frame_iterator,
    get_duration,
    scene_detect_content,
    video_splitter,
)
from pixeltable.functions.whisper import transcribe as whisper_transcribe

from video_benchmark import queries
from video_benchmark.config import AUDIO_SPLIT_FULL_DURATION_SEC, BenchmarkConfig
from video_benchmark.gemini_batch import batched_gemini_frame_context
from video_benchmark.oss_providers import oss_frame_insight_expr, oss_insight_expr
from video_benchmark.paths import DEFAULT_PATHS
from video_benchmark.udfs import (
    FAL_MAX_DURATION_SEC_DEFAULT,
    FAL_VIDEO_UNDERSTANDING_APP,
    GEMINI_25_FLASH_INPUT_PER_M,
    asr_cost_from_transcripts,
    assemble_benchmark_context,
    compact_frame_context,
    cost_delta,
    dedupe_frame_context,
    estimate_image_tokens,
    estimate_nova_video_tokens,
    estimate_text_tokens,
    estimate_video_tokens,
    extract_whisper_segments,
    extract_whisperx_segments,
    fal_run_safe,
    fal_text,
    fal_video_cost,
    fal_video_understanding_input,
    frame_prompt,
    gemini_multimodal_synthesis_contents,
    gemini_orchestrated_cost,
    gemini_output_tokens,
    gemini_prompt_tokens,
    gemini_synthesis_prompt,
    gemini_text,
    gemini_transcribe_prompt,
    merge_transcript_segment_lists,
    native_prompt,
    nova_invoke_safe,
    nova_output_tokens,
    nova_prompt_tokens,
    nova_text,
    oss_synthesis_prompt,
    parse_diarized_transcript,
    resolve_fal_video_url,
    resolved_gemini_cost,
    scene_cut_segment_times,
    select_scene_frames,
    summarize_frame_context,
    vision_cost_from_frames,
    vision_rollup_from_frames,
    zero_cost,
)
from video_benchmark.udfs import (
    nova_cost as nova_cost_expr,
)

CATALOG_DIR = 'video_benchmarking'
OSS_VISION_LABEL = 'OSS-VLM'


@dataclass(frozen=True)
class PathPlan:
    active: frozenset[str]
    want_1: bool
    want_2: bool
    want_3: bool
    want_4: bool
    want_5: bool
    need_modular: bool
    need_gemini_asr: bool
    need_oss_asr: bool
    use_batched_vision: bool
    use_frame_budget: bool


def plan_paths(config: BenchmarkConfig, paths: set[str] | None) -> PathPlan:
    active = frozenset(paths if paths is not None else DEFAULT_PATHS)
    want_3 = '3' in active
    return PathPlan(
        active=active,
        want_1='1' in active,
        want_2='2' in active,
        want_3=want_3,
        want_4='4' in active and config.enable_fal,
        want_5='5' in active and config.enable_nova,
        need_modular=('2' in active) or want_3,
        need_gemini_asr=('2' in active) or (want_3 and config.oss_asr == 'gemini'),
        need_oss_asr=want_3 and config.oss_asr in ('whisper', 'whisperx'),
        use_batched_vision=config.gemini_vision_mode == 'batched',
        use_frame_budget=(
            (config.scene_aware_frames and config.vision_sample_keyframes > 0)
            or (config.max_vision_keyframes > 0 and not config.scene_aware_frames)
        ),
    )


def _audio_splitter(audio, config: BenchmarkConfig):
    mode = config.audio_split_mode
    if mode == 'max_size':
        return audio_splitter(audio=audio, max_size=config.audio_chunk_max_bytes)
    if mode == 'duration':
        return audio_splitter(audio=audio, duration=config.audio_chunk_duration_sec)
    return audio_splitter(audio=audio, duration=AUDIO_SPLIT_FULL_DURATION_SEC)


def _frame_iterator(video_column, config: BenchmarkConfig, *, keyframes_only: bool):
    if keyframes_only:
        return frame_iterator(video_column, keyframes_only=True)
    sample_count = (
        config.vision_sample_keyframes if config.scene_aware_frames else config.max_vision_keyframes
    )
    if sample_count > 0:
        return frame_iterator(video_column, num_frames=sample_count)
    fps = 1.0 / max(config.vision_reference_duration_sec, 1.0)
    return frame_iterator(video_column, fps=fps)


def model_column_names(table_model_base: type, table_name: str) -> set[str]:
    models = table_model_base.__registered_models__
    if table_name not in models:
        return set()
    return set(models[table_name].__columns__)


def build_core_models(config: BenchmarkConfig, plan: PathPlan) -> type:
    """VideoSources + views (no parent rollups that depend on @pxt.query)."""
    TableModel = pxt.model_base()
    threshold = config.scene_detect_threshold
    min_seg = config.min_segment_duration
    fallback = config.segment_fallback_window_sec
    gemini_model = config.gemini_model

    class VideoSources(TableModel, name='video_sources'):
        video: pxt.Video
        query: pxt.String
        scene_cuts = scene_detect_content(video, threshold=threshold)
        video_duration_sec = get_duration(video)
        segment_times = scene_cut_segment_times(
            scene_cuts, video_duration_sec, min_seg, fallback
        )
        if plan.want_1:
            native_response = generate_content(
                model=gemini_model,
                contents=[video, native_prompt(query)],
            )
            native_insight = gemini_text(native_response)
            native_input_tokens = estimate_video_tokens(video_duration_sec, query)
            native_output_tokens = estimate_text_tokens(native_insight)
            native_actual_input_tokens = gemini_prompt_tokens(native_response)
            native_actual_output_tokens = gemini_output_tokens(native_response)
            native_cost = resolved_gemini_cost(
                native_actual_input_tokens,
                native_actual_output_tokens,
                native_input_tokens,
                native_output_tokens,
                GEMINI_25_FLASH_INPUT_PER_M,
            )
        if plan.need_modular:
            audio = extract_audio(video, format='mp3')
        if plan.want_4:
            fal_video_url = resolve_fal_video_url(
                video, config.fal_video_url, FAL_MAX_DURATION_SEC_DEFAULT
            )
            fal_request = fal_video_understanding_input(
                fal_video_url,
                native_prompt(query),
                config.fal_detailed_analysis,
            )
            fal_response = fal_run_safe(fal_request, FAL_VIDEO_UNDERSTANDING_APP)
            fal_insight = fal_text(fal_response)
            fal_cost = fal_video_cost(video_duration_sec, FAL_MAX_DURATION_SEC_DEFAULT)
            if plan.want_1:
                cost_delta_native_vs_fal = cost_delta(native_cost, fal_cost)
        if plan.want_5:
            nova_response = nova_invoke_safe(
                video,
                native_prompt(query),
                config.nova_model_id,
                config.nova_video_s3_uri,
            )
            nova_insight = nova_text(nova_response)
            nova_input_tokens = estimate_nova_video_tokens(video_duration_sec, query)
            nova_output_tokens_est = estimate_text_tokens(nova_insight)
            nova_actual_input_tokens = nova_prompt_tokens(nova_response)
            nova_actual_output_tokens = nova_output_tokens(nova_response)
            nova_cost = nova_cost_expr(
                nova_actual_input_tokens,
                nova_actual_output_tokens,
                nova_input_tokens,
                nova_output_tokens_est,
                config.nova_model_id,
                config.nova_input_usd_per_1m,
                config.nova_output_usd_per_1m,
            )
            if plan.want_1:
                cost_delta_native_vs_nova = cost_delta(native_cost, nova_cost)

    if not plan.need_modular:
        return TableModel

    whisperx_transcribe = None
    if plan.need_oss_asr and config.oss_asr == 'whisperx':
        from pixeltable.functions.whisperx import transcribe as whisperx_transcribe

    class AudioChunks(
        TableModel,
        name='audio_chunks',
        base=VideoSources,
        iterator=_audio_splitter(VideoSources.audio, config),
    ):
        if plan.need_gemini_asr:
            gemini_chunk_transcript = gemini_transcribe(
                audio=audio_segment,
                model=gemini_model,
                prompt=gemini_transcribe_prompt(),
            )
            gemini_transcript_lines = parse_diarized_transcript(
                gemini_chunk_transcript, segment_start
            )
        if plan.need_oss_asr and config.oss_asr == 'whisper':
            whisper_asr_raw = whisper_transcribe(audio=audio_segment, model=config.whisper_model)
            whisper_segment_lines = extract_whisper_segments(whisper_asr_raw, segment_start)
        if plan.need_oss_asr and config.oss_asr == 'whisperx':
            if config.whisperx_num_speakers is not None:
                whisperx_diarized = whisperx_transcribe(
                    audio=audio_segment,
                    model=config.whisperx_model,
                    diarize=True,
                    diarization_model_name=config.whisperx_diarization_model,
                    min_speakers=config.whisperx_min_speakers,
                    num_speakers=config.whisperx_num_speakers,
                )
            else:
                whisperx_diarized = whisperx_transcribe(
                    audio=audio_segment,
                    model=config.whisperx_model,
                    diarize=True,
                    diarization_model_name=config.whisperx_diarization_model,
                    min_speakers=config.whisperx_min_speakers,
                )
            whisperx_segment_lines = extract_whisperx_segments(whisperx_diarized, segment_start)

    if plan.use_frame_budget:
        class Keyframes(
            TableModel,
            name='keyframes',
            base=VideoSources,
            iterator=_frame_iterator(VideoSources.video, config, keyframes_only=False),
        ):
            frame_position_sec = frame_attrs['time'].astype(pxt.Float)
            segment_start = 0.0
            global_position_sec = frame_position_sec.astype(pxt.Float)
            global_position_ms = (global_position_sec * 1000.0).astype(pxt.Float)
            if plan.want_2 and not plan.use_batched_vision:
                gemini_frame_response = generate_content(
                    model=gemini_model,
                    contents=[frame, frame_prompt(query, global_position_sec)],
                )
                gemini_frame_insight = gemini_text(gemini_frame_response)
                gemini_frame_input_tokens = estimate_image_tokens(query)
                gemini_frame_output_tokens = estimate_text_tokens(gemini_frame_insight)
                gemini_frame_actual_input_tokens = gemini_prompt_tokens(gemini_frame_response)
                gemini_frame_actual_output_tokens = gemini_output_tokens(gemini_frame_response)
                gemini_frame_cost = resolved_gemini_cost(
                    gemini_frame_actual_input_tokens,
                    gemini_frame_actual_output_tokens,
                    gemini_frame_input_tokens,
                    gemini_frame_output_tokens,
                    GEMINI_25_FLASH_INPUT_PER_M,
                )
            if plan.want_3:
                oss_frame_insight = oss_frame_insight_expr(
                    frame,
                    query,
                    global_position_sec,
                    backend=config.oss_backend,
                    vision_model=config.oss_vision_model,
                    vision_repo_id=config.oss_vision_repo_id,
                    vision_repo_filename=config.oss_vision_repo_filename,
                    mmproj_repo_filename=config.oss_vision_mmproj_repo_filename,
                    vision_chat_format=config.oss_vision_chat_format,
                    ollama_host=config.ollama_host,
                )
    else:
        class Segments(
            TableModel,
            name='segments',
            base=VideoSources,
            iterator=video_splitter(
                VideoSources.video,
                segment_times=VideoSources.segment_times,
                mode='accurate',
                min_segment_duration=min_seg,
            ),
        ):
            pass

        class Keyframes(
            TableModel,
            name='keyframes',
            base=Segments,
            iterator=_frame_iterator(Segments.video_segment, config, keyframes_only=True),
        ):
            frame_position_sec = frame_attrs['time'].astype(pxt.Float)
            global_position_sec = (segment_start + frame_position_sec).astype(pxt.Float)
            global_position_ms = (global_position_sec * 1000.0).astype(pxt.Float)
            if plan.want_2 and not plan.use_batched_vision:
                gemini_frame_response = generate_content(
                    model=gemini_model,
                    contents=[frame, frame_prompt(query, global_position_sec)],
                )
                gemini_frame_insight = gemini_text(gemini_frame_response)
                gemini_frame_input_tokens = estimate_image_tokens(query)
                gemini_frame_output_tokens = estimate_text_tokens(gemini_frame_insight)
                gemini_frame_actual_input_tokens = gemini_prompt_tokens(gemini_frame_response)
                gemini_frame_actual_output_tokens = gemini_output_tokens(gemini_frame_response)
                gemini_frame_cost = resolved_gemini_cost(
                    gemini_frame_actual_input_tokens,
                    gemini_frame_actual_output_tokens,
                    gemini_frame_input_tokens,
                    gemini_frame_output_tokens,
                    GEMINI_25_FLASH_INPUT_PER_M,
                )
            if plan.want_3:
                oss_frame_insight = oss_frame_insight_expr(
                    frame,
                    query,
                    global_position_sec,
                    backend=config.oss_backend,
                    vision_model=config.oss_vision_model,
                    vision_repo_id=config.oss_vision_repo_id,
                    vision_repo_filename=config.oss_vision_repo_filename,
                    mmproj_repo_filename=config.oss_vision_mmproj_repo_filename,
                    vision_chat_format=config.oss_vision_chat_format,
                    ollama_host=config.ollama_host,
                )

    return TableModel


def build_rollup_models(config: BenchmarkConfig, plan: PathPlan) -> type:
    """Additive VideoSources columns that depend on registered @pxt.query helpers."""
    TableModel = pxt.model_base()
    threshold = config.scene_detect_threshold
    min_seg = config.min_segment_duration
    fallback = config.segment_fallback_window_sec
    gemini_model = config.gemini_model

    class VideoSources(TableModel, name='video_sources'):
        video: pxt.Video
        query: pxt.String
        scene_cuts = scene_detect_content(video, threshold=threshold)
        video_duration_sec = get_duration(video)
        segment_times = scene_cut_segment_times(
            scene_cuts, video_duration_sec, min_seg, fallback
        )
        if plan.want_1:
            native_response = generate_content(
                model=gemini_model,
                contents=[video, native_prompt(query)],
            )
            native_insight = gemini_text(native_response)
            native_input_tokens = estimate_video_tokens(video_duration_sec, query)
            native_output_tokens = estimate_text_tokens(native_insight)
            native_actual_input_tokens = gemini_prompt_tokens(native_response)
            native_actual_output_tokens = gemini_output_tokens(native_response)
            native_cost = resolved_gemini_cost(
                native_actual_input_tokens,
                native_actual_output_tokens,
                native_input_tokens,
                native_output_tokens,
                GEMINI_25_FLASH_INPUT_PER_M,
            )
        if plan.need_modular:
            audio = extract_audio(video, format='mp3')
        if plan.want_4:
            fal_video_url = resolve_fal_video_url(
                video, config.fal_video_url, FAL_MAX_DURATION_SEC_DEFAULT
            )
            fal_request = fal_video_understanding_input(
                fal_video_url,
                native_prompt(query),
                config.fal_detailed_analysis,
            )
            fal_response = fal_run_safe(fal_request, FAL_VIDEO_UNDERSTANDING_APP)
            fal_insight = fal_text(fal_response)
            fal_cost = fal_video_cost(video_duration_sec, FAL_MAX_DURATION_SEC_DEFAULT)
            if plan.want_1:
                cost_delta_native_vs_fal = cost_delta(native_cost, fal_cost)
        if plan.want_5:
            nova_response = nova_invoke_safe(
                video,
                native_prompt(query),
                config.nova_model_id,
                config.nova_video_s3_uri,
            )
            nova_insight = nova_text(nova_response)
            nova_input_tokens = estimate_nova_video_tokens(video_duration_sec, query)
            nova_output_tokens_est = estimate_text_tokens(nova_insight)
            nova_actual_input_tokens = nova_prompt_tokens(nova_response)
            nova_actual_output_tokens = nova_output_tokens(nova_response)
            nova_cost = nova_cost_expr(
                nova_actual_input_tokens,
                nova_actual_output_tokens,
                nova_input_tokens,
                nova_output_tokens_est,
                config.nova_model_id,
                config.nova_input_usd_per_1m,
                config.nova_output_usd_per_1m,
            )
            if plan.want_1:
                cost_delta_native_vs_nova = cost_delta(native_cost, nova_cost)
        if plan.want_2:
            if plan.use_batched_vision:
                gemini_frame_context = batched_gemini_frame_context(
                    query,
                    queries.gemini_frame_batch_inputs(query),
                    gemini_model,
                    config.gemini_vision_batch_size,
                )
            else:
                gemini_frame_context = queries.gemini_frame_insights(query)
            gemini_transcript_context = merge_transcript_segment_lists(
                queries.gemini_audio_transcripts(query)
            )
            gemini_frame_context_deduped = dedupe_frame_context(gemini_frame_context)
            if config.scene_aware_frames:
                gemini_frame_context_selected = select_scene_frames(
                    gemini_frame_context_deduped,
                    scene_cuts,
                    config.frame_select_budget,
                )
                gemini_frame_context_summarized = summarize_frame_context(
                    gemini_frame_context_selected, config.frame_context_max_entries
                )
            else:
                gemini_frame_context_summarized = summarize_frame_context(
                    gemini_frame_context_deduped, config.frame_context_max_entries
                )
            gemini_orchestrated_context = assemble_benchmark_context(
                query,
                gemini_transcript_context,
                gemini_frame_context_summarized,
                'Gemini',
            )
            gemini_synthesis_prompt_text = gemini_synthesis_prompt(
                gemini_orchestrated_context, video_duration_sec
            )
            gemini_synthesis_contents = gemini_multimodal_synthesis_contents(
                gemini_synthesis_prompt_text,
                gemini_frame_context_summarized,
                queries.gemini_frame_images(query),
                config.gemini_synth_max_images,
            )
            gemini_orchestrated_response = generate_content(
                model=gemini_model,
                contents=gemini_synthesis_contents,
            )
            gemini_orchestrated_insight = gemini_text(gemini_orchestrated_response)
            gemini_synthesis_input_tokens = estimate_text_tokens(gemini_orchestrated_context)
            gemini_synthesis_output_tokens = estimate_text_tokens(gemini_orchestrated_insight)
            gemini_synthesis_actual_input_tokens = gemini_prompt_tokens(
                gemini_orchestrated_response
            )
            gemini_synthesis_actual_output_tokens = gemini_output_tokens(
                gemini_orchestrated_response
            )
            gemini_synthesis_cost = resolved_gemini_cost(
                gemini_synthesis_actual_input_tokens,
                gemini_synthesis_actual_output_tokens,
                gemini_synthesis_input_tokens,
                gemini_synthesis_output_tokens,
                GEMINI_25_FLASH_INPUT_PER_M,
            )
            gemini_vision_rollup = vision_rollup_from_frames(gemini_frame_context, 'Gemini')
            gemini_vision_track_cost = vision_cost_from_frames(gemini_frame_context)
            gemini_asr_cost = asr_cost_from_transcripts(
                gemini_transcript_context, video_duration_sec
            )
            gemini_orchestrated_total = gemini_orchestrated_cost(
                gemini_vision_track_cost, gemini_asr_cost, gemini_synthesis_cost
            )
            if plan.want_1:
                cost_delta_native_vs_gemini = cost_delta(native_cost, gemini_orchestrated_total)
        if plan.want_3:
            oss_frame_context = queries.oss_frame_insights(query)
            oss_transcript_context = merge_transcript_segment_lists(
                queries.oss_audio_transcripts(query)
            )
            oss_frame_context_deduped = dedupe_frame_context(oss_frame_context)
            if config.scene_aware_frames:
                oss_frame_context_selected = select_scene_frames(
                    oss_frame_context_deduped,
                    scene_cuts,
                    config.frame_select_budget,
                )
                oss_frame_context_summarized = summarize_frame_context(
                    oss_frame_context_selected, config.oss_frame_context_max_entries
                )
            else:
                oss_frame_context_summarized = summarize_frame_context(
                    oss_frame_context_deduped, config.oss_frame_context_max_entries
                )
            oss_frame_context_compact = compact_frame_context(
                oss_frame_context_summarized, config.oss_frame_insight_max_chars
            )
            oss_context = assemble_benchmark_context(
                query,
                oss_transcript_context,
                oss_frame_context_compact,
                OSS_VISION_LABEL,
            )
            oss_synthesis_prompt_text = oss_synthesis_prompt(oss_context, video_duration_sec)
            oss_insight = oss_insight_expr(
                oss_synthesis_prompt_text,
                backend=config.oss_backend,
                vision_model=config.oss_vision_model,
                synth_repo_id=config.oss_synth_repo_id,
                synth_repo_filename=config.oss_synth_repo_filename,
                synth_max_tokens=config.oss_synth_max_tokens,
                ollama_host=config.ollama_host,
            )
            oss_cost = zero_cost()

    return TableModel


def apply_pursuit_schema(config: BenchmarkConfig, paths: set[str] | None = None) -> PathPlan:
    """Create or reconcile the Pursuit catalog, then register scoped queries."""
    plan = plan_paths(config, paths)
    pxt.create_dir(CATALOG_DIR, if_exists='ignore')
    existing = pxt.get_table(f'{CATALOG_DIR}.video_sources', if_not_exists='ignore')
    existing_cols = set(existing.columns()) if existing is not None else set()
    # Core models omit query-backed rollups. Re-applying them after rollups exist
    # would look like a destructive drop; skip in that case.
    if not existing_cols.intersection({'gemini_orchestrated_insight', 'oss_insight'}):
        build_core_models(config, plan).update_all(CATALOG_DIR)
    if plan.need_modular:
        keyframes = pxt.get_table(f'{CATALOG_DIR}.keyframes')
        audio_chunks = pxt.get_table(f'{CATALOG_DIR}.audio_chunks')
        queries.register(
            keyframes,
            audio_chunks,
            oss_asr=config.oss_asr,
            include_gemini=plan.want_2,
            include_oss=plan.want_3,
            batched_vision=plan.use_batched_vision,
        )
        rollup = build_rollup_models(config, plan)
        rollup.update_all(CATALOG_DIR)
    return plan
