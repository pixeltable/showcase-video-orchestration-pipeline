"""The shared, provider-free evidence lesson used by the CLI and local workspace."""

# TableModel binds names from iterator and base columns at class definition time.
# ruff: noqa: F821
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import pixeltable as pxt
from pixeltable.functions.audio import audio_splitter
from pixeltable.functions.image import resize
from pixeltable.functions.video import extract_audio, frame_iterator, get_duration

from video_benchmark import local_demo_rules as rules
from video_benchmark.provenance import media_identity


class LocalMediaGraph:
    """One source, four prepared frames, audio segments, and explicit request snapshots."""

    def __init__(self, source: Path, *, catalog: str = 'local_media_demo'):
        rules.preparations.clear()
        rules.reviews.clear()
        TableModel = pxt.model_base()

        class Clips(TableModel, name='clips'):
            clip_id = pxt.Column(type=pxt.String, primary_key=True)
            video: pxt.Video
            minimum_brightness: pxt.Float
            duration_sec = get_duration(video)
            audio = extract_audio(video, format='mp3')

        class Frames(
            TableModel,
            name='frames',
            base=Clips,
            iterator=frame_iterator(Clips.video, num_frames=4),
        ):
            position_sec = frame_attrs.time.astype(pxt.Float)
            thumbnail = resize(frame, (128, 96))
            brightness = rules.mean_brightness(frame)
            eligible = brightness >= minimum_brightness

        class AudioSegments(
            TableModel,
            name='audio_segments',
            base=Clips,
            iterator=audio_splitter(Clips.audio, duration=2.0),
        ):
            pass

        @pxt.query
        def candidate_frames(clip_id: str):
            return (
                Frames.where((Frames.clip_id == clip_id) & Frames.eligible)
                .order_by(Frames.position_sec)
                .select(Frames.position_sec, Frames.brightness)
            )

        class Requests(TableModel, name='requests'):
            request_id = pxt.Column(type=pxt.String, primary_key=True)
            clip_id: pxt.String
            evidence = candidate_frames(clip_id)
            decision = rules.review_result(evidence, request_id)

        pxt.create_dir(catalog)
        for _ in range(2):
            TableModel.update_all(catalog)
        self.clips = pxt.get_table(f'{catalog}.clips')
        self.frames = pxt.get_table(f'{catalog}.frames')
        self.segments = pxt.get_table(f'{catalog}.audio_segments')
        self.requests = pxt.get_table(f'{catalog}.requests')
        self.source = source
        self.source_identity = media_identity(source)
        status = self.clips.insert(
            [{'clip_id': 'demo', 'video': str(source), 'minimum_brightness': 0.0}]
        )
        assert status.num_excs == 0, status
        self.requests.insert(
            [{'request_id': name, 'clip_id': 'demo'} for name in ('first', 'second')]
        )
        self.initial_preparation = self.preparation_snapshot()

    def preparation_snapshot(self) -> dict:
        frames = self.frames
        segments = self.segments
        thumbnails = list(
            frames.order_by(frames.position_sec)
            .select(frames.position_sec, frames.thumbnail, frames.brightness)
            .collect()
        )
        chunks = list(
            segments.order_by(segments.segment_start)
            .select(
                segments.segment_start, segments.segment_end, path=segments.audio_segment.localpath
            )
            .collect()
        )
        return {
            'frames': [
                {
                    'position_sec': row['position_sec'],
                    'thumbnail_size': list(row['thumbnail'].size),
                    'thumbnail_sha256': hashlib.sha256(row['thumbnail'].tobytes()).hexdigest(),
                    'brightness': row['brightness'],
                }
                for row in thumbnails
            ],
            'audio_segments': [
                {
                    'segment_start': row['segment_start'],
                    'segment_end': row['segment_end'],
                    'audio_sha256': media_identity(row['path'])['sha256'],
                }
                for row in chunks
            ],
        }

    def change_policy(self, minimum_brightness: float) -> None:
        if not math.isfinite(minimum_brightness) or not 0 <= minimum_brightness <= 255:
            raise ValueError('Choose a brightness between 0 and 255.')
        self.clips.update(
            {'minimum_brightness': minimum_brightness}, where=self.clips.clip_id == 'demo'
        )

    def refresh(self, request_id: str) -> None:
        if request_id not in {'first', 'second'}:
            raise ValueError('Choose the first or second request.')
        self.requests.recompute_columns('evidence', where=self.requests.request_id == request_id)

    def state(self) -> dict:
        frames = list(
            self.frames.order_by(self.frames.position_sec)
            .select(self.frames.position_sec, self.frames.brightness, self.frames.eligible)
            .collect()
        )
        requests = list(
            self.requests.order_by(self.requests.request_id)
            .select(self.requests.request_id, self.requests.evidence, self.requests.decision)
            .collect()
        )
        eligible = [row for row in frames if row['eligible']]
        current = [
            {'position_sec': row['position_sec'], 'brightness': row['brightness']}
            for row in eligible
        ]
        for row in requests:
            row['stale'] = row['evidence'] != current
            row['evaluations'] = rules.reviews.count(row['request_id'])
        return {
            'pixeltable_version': pxt.__version__,
            'provider_calls': 0,
            'minimum_brightness': next(
                iter(self.clips.select(self.clips.minimum_brightness).collect())
            )['minimum_brightness'],
            'frames': frames,
            'requests': requests,
            'prepared_frames': len(rules.preparations),
            'review_evaluations': list(rules.reviews),
            'audio_segments': self.initial_preparation['audio_segments'],
            'source_and_preparation_unchanged': (
                media_identity(self.source) == self.source_identity
                and self.preparation_snapshot() == self.initial_preparation
            ),
        }
