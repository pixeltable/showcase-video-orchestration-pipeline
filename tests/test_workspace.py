"""Use the real graph over HTTP: snapshots, media safety, and local write boundaries."""

import json

import pytest
from fastapi.testclient import TestClient

from video_benchmark.local_graph import LocalMediaGraph
from video_benchmark.workspace import create_app


@pytest.fixture(scope='module')
def workspace(test_video, tmp_path_factory):
    home = tmp_path_factory.mktemp('workspace')
    graph = LocalMediaGraph(test_video, catalog='http_workspace_test')
    app = create_app(graph, home, origin='http://testserver')
    return TestClient(app), graph


def test_rule_and_explicit_refresh_preserve_preparation_and_other_request(workspace):
    client, graph = workspace
    before = client.get('/api/state').json()
    assert before['prepared_frames'] == 4 and before['provider_calls'] == 0
    response = client.post(
        '/api/policy', json={'minimum_brightness': 128}, headers={'Origin': 'http://testserver'}
    )
    assert response.status_code == 200
    state = response.json()
    assert sum(frame['eligible'] for frame in state['frames']) == 2
    assert all(request['stale'] and len(request['evidence']) == 4 for request in state['requests'])
    state = client.post(
        '/api/refresh', json={'request_id': 'first'}, headers={'Origin': 'http://testserver'}
    ).json()
    assert [(r['request_id'], len(r['evidence']), r['stale']) for r in state['requests']] == [
        ('first', 2, False),
        ('second', 4, True),
    ]
    assert state['review_evaluations'] == ['first', 'second', 'first']
    assert state['prepared_frames'] == 4 and state['source_and_preparation_unchanged']
    assert graph.preparation_snapshot() == graph.initial_preparation
    assert client.get('/api/state').json() == state  # reads do not refresh stored results
    for media in ('clip', 'audio', 'frame-0', 'frame-3'):
        response = client.get(f'/media/{media}')
        assert response.status_code == 200 and response.content
    assert client.get('/').status_code == 200


@pytest.mark.parametrize('value', [-1, 256, True, '128', float('nan'), float('inf')])
def test_invalid_policy_never_changes_graph(workspace, value):
    client, _ = workspace
    before = client.get('/api/state').json()
    response = client.post(
        '/api/policy',
        content=json.dumps({'minimum_brightness': value}),
        headers={'Origin': 'http://testserver', 'Content-Type': 'application/json'},
    )
    assert response.status_code == 422
    assert client.get('/api/state').json() == before


def test_local_origin_host_and_media_allowlist(workspace):
    client, _ = workspace
    for origin in ('http://unrelated.example', 'null', None):
        headers = {'Origin': origin} if origin else {}
        assert (
            client.post('/api/policy', json={'minimum_brightness': 0}, headers=headers).status_code
            == 403
        )
    assert client.get('/api/state', headers={'Host': 'unrelated.example'}).status_code == 403
    assert (
        client.post(
            '/api/refresh', json={'request_id': '../first'}, headers={'Origin': 'http://testserver'}
        ).status_code
        == 422
    )
    assert (
        client.post(
            '/api/policy',
            content='x' * 1025,
            headers={'Origin': 'http://testserver', 'Content-Type': 'application/json'},
        ).status_code
        == 413
    )
    assert client.get('/media/unknown').status_code == 404
    assert client.get('/media/%2E%2E%2F.env').status_code == 404
    assert client.post(
        '/api/policy', content='x' * 4096,
        headers={'Origin': 'http://testserver', 'Content-Type': 'application/json',
                 'Content-Length': '1'},
    ).status_code == 413
