"""Tests for OSS provider module."""

from PIL import Image

from video_benchmark import oss_providers


def test_oss_providers_exports():
    assert callable(oss_providers.oss_frame_insight_expr)
    assert callable(oss_providers.oss_insight_expr)
    assert callable(oss_providers.oss_frame_insight_llama)
    assert callable(oss_providers.oss_insight_llama)


def test_frame_to_image_url_data_uri():
    img = Image.new('RGB', (8, 8), color='blue')
    url = oss_providers._frame_to_image_url_impl(img)
    assert url.startswith('data:image/png;base64,')


def test_vision_messages_shape():
    img = Image.new('RGB', (8, 8), color='red')
    messages = oss_providers._vision_messages(img, 'What happens?', 12.5)
    assert messages[0]['role'] == 'user'
    content = messages[0]['content']
    assert content[0]['type'] == 'text'
    assert '12.5s' in content[0]['text']
    assert content[1]['type'] == 'image_url'
    assert content[1]['image_url']['url'].startswith('data:image/png;base64,')


def test_vision_n_ctx_for_qwen():
    assert oss_providers._vision_n_ctx('qwen2.5-vl') == 4096
    assert oss_providers._vision_n_ctx('moondream') == 2048


def test_vision_chat_handler_unsupported():
    try:
        oss_providers._vision_chat_handler('kimi', 'repo', '*mmproj*.gguf')
        raised = False
    except ValueError as exc:
        raised = True
        assert 'Unsupported' in str(exc)
    assert raised
