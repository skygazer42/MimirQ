from __future__ import annotations

import argparse
import hashlib
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("content-length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _stable_embedding(text: str, dim: int) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    out: list[float] = []
    for i in range(dim):
        b = digest[i % len(digest)]
        out.append(((b / 255.0) * 2.0) - 1.0)  # [-1, 1]
    return out


def _extract_last_user_message(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if (msg.get("role") or "").lower() != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        # OpenAI may send rich content; best-effort stringify.
        return json.dumps(content, ensure_ascii=False)
    return ""


class MockOpenAIHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401
        # Keep logs minimal for CI/smoke runs.
        return

    def _send_json(self, status: int, obj: Any) -> None:
        body = _json_bytes(obj)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        self.close_connection = True

    def _send_text(self, status: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        self.close_connection = True

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/health", "/healthz"}:
            self._send_text(200, "ok")
            return
        if self.path == "/v1/models":
            now = int(time.time())
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {"id": "mock-gpt", "object": "model", "created": now, "owned_by": "mock"},
                        {"id": "mock-embedding", "object": "model", "created": now, "owned_by": "mock"},
                    ],
                },
            )
            return
        self._send_json(404, {"error": {"message": "not found", "type": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/v1/embeddings":
            payload = _read_json(self)
            model = payload.get("model") or "mock-embedding"
            inp = payload.get("input", "")
            items: list[str]
            if isinstance(inp, list):
                items = [str(x) for x in inp]
            else:
                items = [str(inp)]
            dim = int(payload.get("dimensions") or 32)
            data = []
            for idx, text in enumerate(items):
                data.append(
                    {"object": "embedding", "index": idx, "embedding": _stable_embedding(text, dim)}
                )
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": data,
                    "model": model,
                    "usage": {"prompt_tokens": 0, "total_tokens": 0},
                },
            )
            return

        if self.path == "/v1/chat/completions":
            payload = _read_json(self)
            model = payload.get("model") or "mock-gpt"
            stream = bool(payload.get("stream"))
            last_user = _extract_last_user_message(payload.get("messages"))
            content = f"[mock] {last_user}".strip() if last_user else "[mock] ok"
            now = int(time.time())
            cid = f"chatcmpl-mock-{hashlib.md5(content.encode('utf-8')).hexdigest()[:16]}"  # noqa: S324

            if not stream:
                self._send_json(
                    200,
                    {
                        "id": cid,
                        "object": "chat.completion",
                        "created": now,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": content},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    },
                )
                return

            # Streamed response in OpenAI-compatible SSE format.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            def send_event(obj: Any) -> None:
                data = _json_bytes(obj)
                self.wfile.write(b"data: " + data + b"\n\n")
                self.wfile.flush()

            send_event(
                {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "created": now,
                    "model": model,
                    "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
                }
            )
            for part in content.split(" "):
                send_event(
                    {
                        "id": cid,
                        "object": "chat.completion.chunk",
                        "created": now,
                        "model": model,
                        "choices": [{"index": 0, "delta": {"content": part + " "}, "finish_reason": None}],
                    }
                )
            send_event(
                {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "created": now,
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
            )
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.close_connection = True
            return

        self._send_json(404, {"error": {"message": "not found", "type": "not_found"}})


def main() -> int:
    parser = argparse.ArgumentParser(description="Local OpenAI-compatible mock server for smoke tests.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), MockOpenAIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

