"""Offline check of the Claude request/response handling against a local fake Messages API."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.translation.base import Chunk, RateLimited, TranslatorError
from app.translation.claude import ClaudeTranslator


class FakeAnthropic(BaseHTTPRequestHandler):
    requests: list = []
    reply: dict = {}
    status = 200

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        FakeAnthropic.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        payload = json.dumps(FakeAnthropic.reply).encode()
        self.send_response(FakeAnthropic.status)
        self.send_header("content-type", "application/json")
        if FakeAnthropic.status == 429:
            self.send_header("retry-after", "7")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@pytest.fixture
def fake_api():
    server = HTTPServer(("127.0.0.1", 0), FakeAnthropic)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    FakeAnthropic.requests = []
    FakeAnthropic.status = 200
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def message(text: str, stop_reason: str = "end_turn") -> dict:
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": text}], "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


REPLY = {"s": [{"t": "The cat is sleeping.", "u": [["Le chat", "the cat"], ["dort.", "sleeps."]]}], "g": [["Minou", "Kitty"]]}
CHUNK = Chunk(["Le chat dort."], [0], "french", "english", {"Médor": "Rover"}, "Il pleut.", "It rains.")


def test_request_shape_with_fallbacks(fake_api):
    FakeAnthropic.reply = message(json.dumps(REPLY))
    t = ClaudeTranslator("sk-test", "claude-opus-5-5", "low", "default", base_url=fake_api)
    result = t.translate(CHUNK)
    assert result.sentences == REPLY["s"] and result.glossary == {"Minou": "Kitty"}

    req = FakeAnthropic.requests[0]
    body = req["body"]
    assert req["path"].startswith("/v1/messages")
    assert "server-side-fallback-2026-07-01" in req["headers"].get("anthropic-beta", "")
    assert body["model"] == "claude-opus-5-5" and body["fallbacks"] == "default"
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["schema"]["required"] == ["s", "g"]
    assert "French into English" in body["system"][0]["text"]
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    content = body["messages"][0]["content"]
    assert "Médor = Rover" in content and "Il pleut." in content and "It rains." in content
    assert content.endswith("Sentences:\n1. Le chat dort.")
    assert "temperature" not in body and "thinking" not in body


def test_no_fallbacks_for_other_models(fake_api):
    FakeAnthropic.reply = message(json.dumps(REPLY))
    ClaudeTranslator("sk-test", "claude-haiku-5-5", "", base_url=fake_api).translate(CHUNK)
    req = FakeAnthropic.requests[0]
    assert "fallbacks" not in req["body"] and "output_config" in req["body"]
    assert "effort" not in req["body"]["output_config"]
    assert "anthropic-beta" not in req["headers"]


def test_error_mapping(fake_api):
    t = ClaudeTranslator("sk-test", "claude-opus-5-5", base_url=fake_api)
    t.client = t.client.with_options(max_retries=0)
    FakeAnthropic.reply = message("not json")
    with pytest.raises(TranslatorError):
        t.translate(CHUNK)
    FakeAnthropic.reply = message("{}", stop_reason="refusal")
    with pytest.raises(TranslatorError, match="declined"):
        t.translate(CHUNK)
    FakeAnthropic.status = 429
    FakeAnthropic.reply = {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}
    with pytest.raises(RateLimited) as exc:
        t.translate(CHUNK)
    assert exc.value.retry_after == 7
