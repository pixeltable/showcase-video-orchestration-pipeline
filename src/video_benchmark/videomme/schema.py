"""Video-MME catalog: one TableModel graph, applied with a single `update_all()`.

    videos          one row per video, with its scene cuts (paths 2, 3)
      keyframes     view: frames sampled evenly, captioned once per video (paths 2, 3)
      audio_chunks  view: the audio as one chunk, transcribed once per video (paths 2, 3)
    questions       one row per question: every path's answer, letter, correctness, and cost

Questions are inserted after their videos, so their queries see finished captions and
transcripts. The paid evidence (captions, transcript) is computed once per video and reused by
all of its questions; only the answer call is per question.
"""

# TableModel class bodies bind iterator and base columns that ruff cannot see.
# ruff: noqa: F821

from __future__ import annotations

import pixeltable as pxt
from pixeltable.functions.audio import audio_splitter
from pixeltable.functions.bedrock import converse
from pixeltable.functions.gemini import generate_content
from pixeltable.functions.video import (
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
from video_benchmark.schema import PathPlan, apply_models
from video_benchmark.videomme import prompts as mcq
from video_benchmark.videomme import scoring

CATALOG_DIR = 'videomme'
# The local 7B synthesis model has an 8K-token context; its evidence is windowed to fit.
OSS_EVIDENCE_MAX_CHARS = 16_000


def build_models(config: BenchmarkConfig, plan: PathPlan) -> type:
    TableModel = pxt.model_base()
    model = config.gemini_model
    definition = provenance.pipeline_identity(
        config_manifest_dict(config), plan.enabled(), pxt.__version__
    )

    class Videos(TableModel, name='videos'):
        video_id = pxt.Column(type=pxt.String, primary_key=True)
        video: pxt.Video
        duration_bucket: pxt.String
        domain: pxt.String
        url: pxt.String
        definition_id = definition
        duration_sec = get_duration(video)
        if plan.modular:
            audio = extract_audio(video, format='mp3')
            scene_cuts = scene_detect_content(video, threshold=config.scene_detect_threshold)

    if plan.modular:

        class AudioChunks(
            TableModel,
            name='audio_chunks',
            base=Videos,
            iterator=audio_splitter(Videos.audio, duration=AUDIO_SPLIT_FULL_DURATION_SEC),
        ):
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

        class Keyframes(
            TableModel,
            name='keyframes',
            base=Videos,
            iterator=frame_iterator(Videos.video, num_frames=config.vision_sample_keyframes),
        ):
            position_sec = frame_attrs['time'].astype(pxt.Float)
            if plan.orchestrated:
                gemini_caption_response = generate_content(
                    [frame, mcq.frame_prompt(position_sec)],
                    model=model,
                    config=providers.NO_THINKING,
                )
                gemini_caption = providers.gemini_text(gemini_caption_response)
                gemini_caption_usage = pricing.gemini_usage(gemini_caption_response)
                gemini_caption_cost = pricing.gemini_cost(gemini_caption_usage, model)
            if plan.oss:
                oss_caption = oss.local_caption(
                    frame,
                    mcq.frame_prompt(position_sec),
                    repo_id=config.oss_vision_repo_id,
                    filename=config.oss_vision_repo_filename,
                    mmproj_filename=config.oss_vision_mmproj_repo_filename,
                    chat_format=config.oss_vision_chat_format,
                )

        @pxt.query
        def asr_rows(video_id: str):
            return (
                AudioChunks.where(AudioChunks.video_id == video_id)
                .order_by(AudioChunks.segment_start)
                .select(lines=AudioChunks.gemini_transcript, cost=AudioChunks.gemini_asr_cost)
            )

        @pxt.query
        def frame_images(video_id: str):
            return (
                Keyframes.where(Keyframes.video_id == video_id)
                .order_by(Keyframes.position_sec)
                .select(position_sec=Keyframes.position_sec, frame=Keyframes.frame)
            )

        if plan.orchestrated:

            @pxt.query
            def gemini_frame_rows(video_id: str):
                return (
                    Keyframes.where(
                        (Keyframes.video_id == video_id) & (Keyframes.gemini_caption != None)  # noqa: E711
                    )
                    .order_by(Keyframes.position_sec)
                    .select(
                        position_sec=Keyframes.position_sec,
                        caption=Keyframes.gemini_caption,
                        cost=Keyframes.gemini_caption_cost,
                    )
                )

        if plan.oss:

            @pxt.query
            def oss_frame_rows(video_id: str):
                return (
                    Keyframes.where(
                        (Keyframes.video_id == video_id) & (Keyframes.oss_caption != None)  # noqa: E711
                    )
                    .order_by(Keyframes.position_sec)
                    .select(position_sec=Keyframes.position_sec, caption=Keyframes.oss_caption)
                )

        @pxt.query(return_scalar=True)
        def video_scene_cuts(video_id: str):
            return Videos.where(Videos.video_id == video_id).select(Videos.scene_cuts)

    class Questions(TableModel, name='questions'):
        question_id = pxt.Column(type=pxt.String, primary_key=True)
        video_id: pxt.String
        video: pxt.Video
        duration_bucket: pxt.String
        domain: pxt.String
        task_type: pxt.String
        question: pxt.String
        options: pxt.Json
        answer: pxt.String
        question_prompt = mcq.question_block(question, options)
        if plan.native:
            native_response = generate_content([video, question_prompt], model=model)
            native_raw = providers.gemini_text(native_response)
            native_letter = scoring.extract_letter(native_raw)
            native_correct = scoring.is_correct(native_letter, answer)
            native_usage = pricing.gemini_usage(native_response)
            native_cost = pricing.gemini_cost(native_usage, model)
        if plan.native_low:
            native_low_response = generate_content(
                [video, question_prompt], model=model, config=providers.LOW_MEDIA_RESOLUTION
            )
            native_low_raw = providers.gemini_text(native_low_response)
            native_low_letter = scoring.extract_letter(native_low_raw)
            native_low_correct = scoring.is_correct(native_low_letter, answer)
            native_low_usage = pricing.gemini_usage(native_low_response)
            native_low_cost = pricing.gemini_cost(native_low_usage, model)
        if plan.modular:
            duration_sec = get_duration(video)
            asr = asr_rows(video_id)
            transcript = evidence.merge_transcript_rows(asr)
            asr_cost = pricing.sum_costs(asr)
            scene_cuts = video_scene_cuts(video_id)[0]
        if plan.orchestrated:
            orch_frames = gemini_frame_rows(video_id)
            orch_selected = evidence.select_frames(
                orch_frames, scene_cuts, config.frame_select_budget
            )
            orch_attached = evidence.attached_frames(orch_selected, config.gemini_synth_max_images)
            orch_evidence = evidence.evidence_text(transcript, orch_selected, 'Gemini')
            orch_prompt = mcq.orchestrated_prompt(
                question, options, orch_evidence, duration_sec, orch_attached
            )
            orch_contents = evidence.synthesis_contents(
                orch_prompt, orch_attached, frame_images(video_id)
            )
            orch_response = generate_content(orch_contents, model=model)
            orch_raw = providers.gemini_text(orch_response)
            orch_letter = scoring.extract_letter(orch_raw)
            orch_correct = scoring.is_correct(orch_letter, answer)
            orch_usage = pricing.gemini_usage(orch_response)
            orch_cost = pricing.gemini_cost(orch_usage, model)
            # The video's captions and transcript; the export splits it across its questions.
            orch_shared_cost = pricing.sum_costs(orch_frames) + asr_cost
        if plan.oss:
            oss_frames = oss_frame_rows(video_id)
            oss_selected = evidence.compact_frames(
                evidence.select_frames(oss_frames, scene_cuts, config.frame_select_budget),
                config.oss_frame_caption_max_chars,
            )
            oss_evidence = scoring.window_text(
                evidence.evidence_text(transcript, oss_selected, 'OSS-VLM'), OSS_EVIDENCE_MAX_CHARS
            )
            oss_prompt = mcq.orchestrated_prompt(question, options, oss_evidence, duration_sec, [])
            oss_raw = oss.local_synthesize(
                oss_prompt,
                repo_id=config.oss_synth_repo_id,
                filename=config.oss_synth_repo_filename,
                max_tokens=config.oss_synth_max_tokens,
            )
            oss_letter = scoring.extract_letter(oss_raw)
            oss_correct = scoring.is_correct(oss_letter, answer)
            # Path 3 shares the Gemini transcript on Video-MME: its only API spend.
            oss_shared_cost = asr_cost
        if plan.nova:
            # None above Bedrock's inline limit: Pixeltable skips the call, no error, no cost.
            nova_video = providers.nova_inline_video(video)
            nova_response = converse(
                providers.nova_video_messages(nova_video, question_prompt),
                model_id=config.nova_model_id,
            )
            nova_raw = providers.nova_text(nova_response)
            nova_letter = scoring.extract_letter(nova_raw)
            nova_correct = scoring.is_correct(nova_letter, answer)
            nova_usage = pricing.nova_usage(nova_response)
            nova_cost = pricing.nova_cost(nova_usage, config.nova_model_id)

    return TableModel


def apply_schema(config: BenchmarkConfig, plan: PathPlan) -> None:
    apply_models(build_models(config, plan), CATALOG_DIR)


def reset_catalog() -> None:
    pxt.drop_dir(CATALOG_DIR, force=True, if_not_exists='ignore')
