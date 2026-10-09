"""Pursuit catalog: one TableModel graph, applied with a single `update_all()`.

    runs            one row per (video, query) run: native paths 1, 1L, 4, 5, and the audio track
      keyframes     view: frames sampled evenly from the run's video, captioned (paths 2, 3)
      audio_chunks  view: the run's audio as one chunk, transcribed (paths 2, 3)
    syntheses       one row per run for paths 2 and 3; its columns query keyframes and audio_chunks

A syntheses row is inserted after its run row, so its queries see finished views and every
paid call runs once. Columns exist only for the selected paths, so no unrequested path spends.
"""

# TableModel class bodies bind iterator and base columns that ruff cannot see.
# ruff: noqa: F821

from __future__ import annotations

import re
from dataclasses import dataclass

import pixeltable as pxt
from pixeltable.functions import fal, whisper, whisperx
from pixeltable.functions.audio import audio_splitter
from pixeltable.functions.bedrock import converse
from pixeltable.functions.gemini import generate_content
from pixeltable.functions.video import (
    clip,
    extract_audio,
    frame_iterator,
    get_duration,
    scene_detect_content,
)

from video_benchmark import evidence, oss, pricing, prompts, provenance, providers
from video_benchmark.config import (
    AUDIO_SPLIT_FULL_DURATION_SEC,
    BenchmarkConfig,
    config_manifest_dict,
)
from video_benchmark.paths import DEFAULT_PATHS

CATALOG_DIR = 'video_benchmarking'
FAL_APP = 'fal-ai/video-understanding'
# fal-ai/video-understanding rejects clips longer than about 122 s.
FAL_MAX_DURATION_SEC = 120.0


@dataclass(frozen=True)
class PathPlan:
    active: frozenset[str]
    native: bool
    native_low: bool
    orchestrated: bool
    oss: bool
    fal: bool
    nova: bool
    oss_asr: str

    @property
    def modular(self) -> bool:
        return self.orchestrated or self.oss

    @property
    def gemini_asr(self) -> bool:
        return self.orchestrated or (self.oss and self.oss_asr == 'gemini')

    def enabled(self) -> list[str]:
        """Paths that will run, in label order (4 and 5 also need credentials)."""
        flags = {
            '1': self.native,
            '1L': self.native_low,
            '2': self.orchestrated,
            '3': self.oss,
            '4': self.fal,
            '5': self.nova,
        }
        return [path for path, on in flags.items() if on]


def plan_paths(config: BenchmarkConfig, paths: set[str] | None) -> PathPlan:
    active = frozenset(paths if paths is not None else DEFAULT_PATHS)
    return PathPlan(
        active=active,
        native='1' in active,
        native_low='1L' in active,
        orchestrated='2' in active,
        oss='3' in active,
        fal='4' in active and config.enable_fal,
        nova='5' in active and config.enable_nova,
        oss_asr=config.oss_asr,
    )


class CatalogSchemaMismatch(RuntimeError):
    """The live catalog was built for different paths or settings."""


def build_models(config: BenchmarkConfig, plan: PathPlan) -> type:
    TableModel = pxt.model_base()
    model = config.gemini_model
    definition = provenance.pipeline_identity(
        config_manifest_dict(config), plan.enabled(), pxt.__version__
    )

    class Runs(TableModel, name='runs'):
        run_id = pxt.Column(type=pxt.String, primary_key=True)
        video: pxt.Video
        query: pxt.String
        definition_id = definition
        duration_sec = get_duration(video)
        if plan.native:
            native_response = generate_content([video, prompts.native_prompt(query)], model=model)
            native_answer = providers.gemini_text(native_response)
            native_usage = pricing.gemini_usage(native_response)
            native_cost = pricing.gemini_cost(native_usage, model)
        if plan.native_low:
            native_low_response = generate_content(
                [video, prompts.native_prompt(query)],
                model=model,
                config=providers.LOW_MEDIA_RESOLUTION,
            )
            native_low_answer = providers.gemini_text(native_low_response)
            native_low_usage = pricing.gemini_usage(native_low_response)
            native_low_cost = pricing.gemini_cost(native_low_usage, model)
        if plan.fal:
            fal_clip = clip(video, start_time=0.0, duration=FAL_MAX_DURATION_SEC)
            fal_response = fal.run(
                {
                    'video_url': providers.fal_upload(fal_clip),
                    'prompt': prompts.native_prompt(query),
                },
                app=FAL_APP,
            )
            fal_answer = fal_response.output.astype(pxt.String)
            fal_cost = pricing.fal_cost(duration_sec, FAL_MAX_DURATION_SEC)
        if plan.nova:
            nova_video = providers.nova_inline_video(video)
            nova_response = converse(
                providers.nova_video_messages(nova_video, prompts.native_prompt(query)),
                model_id=config.nova_model_id,
            )
            nova_answer = providers.nova_text(nova_response)
            nova_usage = pricing.nova_usage(nova_response)
            nova_cost = pricing.nova_cost(nova_usage, config.nova_model_id)
        if plan.modular:
            audio = extract_audio(video, format='mp3')

    if not plan.modular:
        return TableModel

    class AudioChunks(
        TableModel,
        name='audio_chunks',
        base=Runs,
        iterator=audio_splitter(Runs.audio, duration=AUDIO_SPLIT_FULL_DURATION_SEC),
    ):
        if plan.gemini_asr:
            gemini_asr_response = providers.transcribe_response(
                audio_segment,
                model=model,
                prompt=prompts.TRANSCRIBE_PROMPT,
                config=providers.NO_THINKING,
            )
            gemini_transcript = evidence.parse_diarized_transcript(
                providers.gemini_text(gemini_asr_response), segment_start
            )
            gemini_asr_usage = pricing.gemini_usage(gemini_asr_response)
            gemini_asr_cost = pricing.gemini_cost(gemini_asr_usage, model)
        if plan.oss and plan.oss_asr == 'whisper':
            whisper_result = whisper.transcribe(audio_segment, model=config.whisper_model)
            whisper_transcript = evidence.asr_segment_lines(whisper_result, segment_start)
        if plan.oss and plan.oss_asr == 'whisperx':
            whisperx_result = whisperx.transcribe(
                audio_segment,
                model=config.whisperx_model,
                diarize=True,
                diarization_model_name=config.whisperx_diarization_model,
                min_speakers=config.whisperx_min_speakers,
                num_speakers=config.whisperx_num_speakers,
            )
            whisperx_transcript = evidence.asr_segment_lines(whisperx_result, segment_start)

    class Keyframes(
        TableModel,
        name='keyframes',
        base=Runs,
        iterator=frame_iterator(Runs.video, num_frames=config.vision_sample_keyframes),
    ):
        position_sec = frame_attrs['time'].astype(pxt.Float)
        if plan.orchestrated:
            gemini_caption_response = generate_content(
                [frame, prompts.frame_prompt(query, position_sec)],
                model=model,
                config=providers.NO_THINKING,
            )
            gemini_caption = providers.gemini_text(gemini_caption_response)
            gemini_caption_usage = pricing.gemini_usage(gemini_caption_response)
            gemini_caption_cost = pricing.gemini_cost(gemini_caption_usage, model)
        if plan.oss:
            oss_caption = oss.local_caption(
                frame,
                prompts.frame_prompt(query, position_sec),
                repo_id=config.oss_vision_repo_id,
                filename=config.oss_vision_repo_filename,
                mmproj_filename=config.oss_vision_mmproj_repo_filename,
                chat_format=config.oss_vision_chat_format,
            )

    if plan.gemini_asr:

        @pxt.query
        def gemini_asr_rows(run_id: str):
            return (
                AudioChunks.where(AudioChunks.run_id == run_id)
                .order_by(AudioChunks.segment_start)
                .select(lines=AudioChunks.gemini_transcript, cost=AudioChunks.gemini_asr_cost)
            )

    if plan.oss and plan.oss_asr != 'gemini':

        @pxt.query
        def local_asr_rows(run_id: str):
            return (
                AudioChunks.where(AudioChunks.run_id == run_id)
                .order_by(AudioChunks.segment_start)
                .select(lines=getattr(AudioChunks, f'{plan.oss_asr}_transcript'))
            )

    @pxt.query
    def frame_images(run_id: str):
        return (
            Keyframes.where(Keyframes.run_id == run_id)
            .order_by(Keyframes.position_sec)
            .select(position_sec=Keyframes.position_sec, frame=Keyframes.frame)
        )

    if plan.orchestrated:
        # A frame whose caption call failed carries no evidence (and was not billed).
        @pxt.query
        def gemini_frame_rows(run_id: str):
            return (
                Keyframes.where((Keyframes.run_id == run_id) & (Keyframes.gemini_caption != None))  # noqa: E711
                .order_by(Keyframes.position_sec)
                .select(
                    position_sec=Keyframes.position_sec,
                    caption=Keyframes.gemini_caption,
                    cost=Keyframes.gemini_caption_cost,
                )
            )

    if plan.oss:

        @pxt.query
        def oss_frame_rows(run_id: str):
            return (
                Keyframes.where((Keyframes.run_id == run_id) & (Keyframes.oss_caption != None))  # noqa: E711
                .order_by(Keyframes.position_sec)
                .select(position_sec=Keyframes.position_sec, caption=Keyframes.oss_caption)
            )

    class Syntheses(TableModel, name='syntheses'):
        run_id = pxt.Column(type=pxt.String, primary_key=True)
        video: pxt.Video
        query: pxt.String
        duration_sec = get_duration(video)
        scene_cuts = scene_detect_content(video, threshold=config.scene_detect_threshold)
        if plan.orchestrated:
            gemini_frames = gemini_frame_rows(run_id)
            gemini_asr = gemini_asr_rows(run_id)
            gemini_transcript = evidence.merge_transcript_rows(gemini_asr)
            gemini_selected = evidence.select_frames(
                gemini_frames, scene_cuts, config.frame_select_budget
            )
            gemini_attached = evidence.attached_frames(
                gemini_selected, config.gemini_synth_max_images
            )
            gemini_prompt = prompts.synthesis_prompt(
                query,
                evidence.evidence_text(gemini_transcript, gemini_selected, 'Gemini'),
                duration_sec,
                gemini_attached,
            )
            gemini_contents = evidence.synthesis_contents(
                gemini_prompt, gemini_attached, frame_images(run_id)
            )
            gemini_response = generate_content(gemini_contents, model=model)
            gemini_answer = providers.gemini_text(gemini_response)
            gemini_synthesis_usage = pricing.gemini_usage(gemini_response)
            gemini_synthesis_cost = pricing.gemini_cost(gemini_synthesis_usage, model)
            gemini_caption_cost = pricing.sum_costs(gemini_frames)
            gemini_asr_cost = pricing.sum_costs(gemini_asr)
            gemini_total_cost = gemini_caption_cost + gemini_asr_cost + gemini_synthesis_cost
        if plan.oss:
            oss_frames = oss_frame_rows(run_id)
            oss_asr = (
                gemini_asr_rows(run_id) if plan.oss_asr == 'gemini' else local_asr_rows(run_id)
            )
            oss_transcript = evidence.merge_transcript_rows(oss_asr)
            oss_selected = evidence.compact_frames(
                evidence.select_frames(oss_frames, scene_cuts, config.frame_select_budget),
                config.oss_frame_caption_max_chars,
            )
            oss_prompt = prompts.synthesis_prompt(
                query,
                evidence.evidence_text(oss_transcript, oss_selected, 'OSS-VLM'),
                duration_sec,
                [],
            )
            oss_answer = oss.local_synthesize(
                oss_prompt,
                repo_id=config.oss_synth_repo_id,
                filename=config.oss_synth_repo_filename,
                max_tokens=config.oss_synth_max_tokens,
            )
            # Local models cost no API spend; Gemini ASR, when chosen for fairness, does.
            if plan.oss_asr == 'gemini':
                oss_cost = pricing.sum_costs(oss_asr)
            else:
                oss_cost = 0.0

    return TableModel


def apply_models(models: type, catalog_dir: str) -> None:
    """Create the catalog from `models`, or confirm the live one already matches them.

    Any difference (other paths, other settings, edited prompts) raises instead of migrating:
    one catalog never mixes rows computed under two definitions.
    """
    pxt.create_dir(catalog_dir, if_exists='ignore')
    declared = set(models.__registered_models__)
    existing = {re.split(r'[./]', path)[-1] for path in pxt.list_tables(catalog_dir)}
    problems = [
        f'table {name!r} is not part of these paths' for name in sorted(existing - declared)
    ]
    for name, diff in models.get_model_diff(catalog_dir).items():
        if diff.resolution not in ('create', 'up_to_date'):
            problems.extend(f'{name}: {op.description}' for op in diff.ops)
    if problems:
        detail = '\n  '.join(problems)
        raise CatalogSchemaMismatch(
            f'Catalog {catalog_dir!r} was built for different paths or settings:\n  {detail}\n'
            f'Rerun with --reset (drops {catalog_dir!r}) to rebuild it.'
        )
    models.update_all(catalog_dir)


def apply_schema(config: BenchmarkConfig, paths: set[str] | None = None) -> PathPlan:
    plan = plan_paths(config, paths)
    apply_models(build_models(config, plan), CATALOG_DIR)
    return plan


def reset_catalog() -> None:
    pxt.drop_dir(CATALOG_DIR, force=True, if_not_exists='ignore')
