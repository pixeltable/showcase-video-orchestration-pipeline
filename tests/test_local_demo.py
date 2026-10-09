"""The developer lesson executes real media transforms and a deliberate query refresh."""

from video_benchmark.local_demo import run_local_demo


def test_media_preparation_is_shared_and_only_selected_request_refreshes(tmp_path):
    result = run_local_demo(tmp_path)
    assert result['provider_calls'] == 0
    assert result['prepared_frames'] == 4
    assert result['review_evaluations'] == ['first', 'second', 'first']
    assert result['requests_after_explicit_refresh']['first'].startswith('2 frames')
    assert result['requests_after_explicit_refresh']['second'].startswith('4 frames')
    assert result['source_and_preparation_unchanged']
