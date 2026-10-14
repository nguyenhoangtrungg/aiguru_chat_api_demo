import json

import httpx
import pytest
from fastapi.testclient import TestClient

from config import Settings
from main import create_app

SETTINGS = Settings("https://model.test/v1", "test-model", "secret-test-key", 2)


@pytest.fixture
def api():
    calls = []

    def backend(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "  Trả lời từ backend.  "}}]})

    with TestClient(create_app(SETTINGS, httpx.MockTransport(backend))) as client:
        yield client, calls


def test_health_does_not_call_model(api):
    client, calls = api
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert not calls


def test_chat_request_and_response(api):
    client, calls = api
    response = client.post("/chat", json={"message": "  Xin  chào\n"})
    assert response.status_code == 200
    assert response.json() == {"answer": "Trả lời từ backend."}
    assert len(calls) == 1
    request = calls[0]
    assert str(request.url) == "https://model.test/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer secret-test-key"
    assert json.loads(request.content) == {
        "model": "test-model", "messages": [{"role": "user", "content": "Xin  chào"}], "stream": False,
    }
    assert request.extensions["timeout"] == dict(connect=2, read=2, write=2, pool=2)


@pytest.mark.parametrize("body", [{}, {"message": None}, {"message": 7}, {"message": True},
    {"message": []}, {"message": {}}, {"message": ""}, {"message": " \t\n "},
    {"message": "a" * 2001}, {"message": "ok", "extra": 1}, [], "text"])
def test_invalid_body_never_calls_backend(api, body):
    client, calls = api
    assert client.post("/chat", json=body).status_code == 422
    assert not calls


@pytest.mark.parametrize("body", [b"", b'{"message":'])
def test_missing_or_malformed_json(api, body):
    client, calls = api
    assert client.post("/chat", content=body, headers={"Content-Type": "application/json"}).status_code == 422
    assert not calls


@pytest.mark.parametrize("length", [1, 2000])
def test_length_after_strip(api, length):
    client, calls = api
    assert client.post("/chat", json={"message": "  " + "á" * length + "\n"}).status_code == 200
    assert len(json.loads(calls[0].content)["messages"][0]["content"]) == length


def test_routes_and_openapi(api):
    client, calls = api
    assert client.get("/chat").status_code == 405
    assert client.get("/missing").status_code == 404
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert schema["paths"]["/chat"]["post"]["requestBody"]["required"] is True
    assert set(schema["paths"]["/chat"]["post"]["responses"]) == {"200", "422", "502", "503", "504"}
    models = schema["components"]["schemas"]
    request = models["ChatRequest"]
    assert request["required"] == ["message"]
    assert request["additionalProperties"] is False
    assert request["properties"]["message"]["minLength"] == 1
    assert request["properties"]["message"]["maxLength"] == 2000
    assert models["ChatResponse"]["required"] == ["answer"]
    assert not calls


@pytest.mark.parametrize("status,expected,code", [(401,502,"model_backend_error"),
    (403,502,"model_backend_error"), (404,502,"model_backend_error"),
    (400,502,"model_backend_error"), (302,502,"model_backend_error"),
    (429,503,"model_unavailable"), (500,503,"model_unavailable"), (503,503,"model_unavailable")])
def test_backend_http_errors(status, expected, code):
    def backend(request):
        return httpx.Response(status, text="secret-test-key PRIVATE BACKEND ERROR", headers={"Location": "https://other.test"})
    with TestClient(create_app(SETTINGS, httpx.MockTransport(backend))) as client:
        response = client.post("/chat", json={"message": "test"})
        assert response.status_code == expected
        assert response.json()["detail"]["code"] == code
        assert "secret-test-key" not in response.text
        assert "PRIVATE" not in response.text


@pytest.mark.parametrize("error,expected", [(httpx.ReadTimeout,504), (httpx.ConnectTimeout,504),
    (httpx.ConnectError,503), (httpx.RemoteProtocolError,503)])
def test_backend_network_errors_and_health(error, expected):
    def backend(request):
        raise error("secret-test-key", request=request)
    with TestClient(create_app(SETTINGS, httpx.MockTransport(backend))) as client:
        assert client.get("/health").status_code == 200
        response = client.post("/chat", json={"message": "test"})
        assert response.status_code == expected
        assert "secret-test-key" not in response.text


@pytest.mark.parametrize("payload", [None, {}, [], {"choices": []}, {"choices": [None]},
    {"choices": [{"message": {"content": None}}]}, {"choices": [{"message": {"content": " "}}]},
    {"choices": [{"message": {"content": []}}]}, {"error": {"message": "provider error in 200"}}])
def test_invalid_backend_payload(payload):
    with TestClient(create_app(SETTINGS, httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))) as client:
        assert client.post("/chat", json={"message": "test"}).status_code == 502


def test_backend_invalid_json():
    with TestClient(create_app(SETTINGS, httpx.MockTransport(lambda r: httpx.Response(200, content=b"not JSON")))) as client:
        assert client.post("/chat", json={"message": "test"}).status_code == 502


def test_self_host_no_key():
    def backend(request):
        assert "authorization" not in request.headers
        assert str(request.url) == "http://127.0.0.1:18080/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    settings = Settings("http://127.0.0.1:18080/v1", "local")
    with TestClient(create_app(settings, httpx.MockTransport(backend))) as client:
        assert client.post("/chat", json={"message": "test"}).status_code == 200


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "LLM_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:18080/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")


@pytest.mark.parametrize("name,value", [("LLM_BASE_URL",""), ("LLM_BASE_URL","localhost"),
    ("LLM_BASE_URL","https://user:secret@host/v1"), ("LLM_BASE_URL","http://host:bad/v1"),
    ("LLM_BASE_URL","https://host/v1?key=secret"), ("LLM_BASE_URL","https://host/v1/chat/completions"),
    ("LLM_MODEL",""), ("LLM_MODEL","REPLACE_MODEL"), ("LLM_API_KEY","REPLACE_KEY"),
    ("LLM_TIMEOUT_SECONDS","nan"), ("LLM_TIMEOUT_SECONDS","inf"),
    ("LLM_TIMEOUT_SECONDS","0"), ("LLM_TIMEOUT_SECONDS","-1"), ("LLM_TIMEOUT_SECONDS","abc")])
def test_bad_settings_fail_at_startup(clean_env, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        with TestClient(create_app()):
            pass


def test_config_file_and_environment_priority(clean_env, monkeypatch, tmp_path):
    path = tmp_path / ".env"
    path.write_text("LLM_BASE_URL=https://openrouter.ai/api/v1\nLLM_MODEL=file-model\nLLM_API_KEY=file-secret\nLLM_TIMEOUT_SECONDS=7\n")
    settings = Settings.load(path)
    assert settings.model == "test-model"
    assert settings.base_url == "http://127.0.0.1:18080/v1"
    assert settings.timeout_seconds == 7
    assert settings.api_key == "file-secret"
    assert "file-secret" not in repr(settings)
    monkeypatch.setenv("LLM_API_KEY", "")
    assert Settings.load(path).api_key == ""


def test_openrouter_requires_key(clean_env, monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        Settings.load(tmp_path / "absent.env")
