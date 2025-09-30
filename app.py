import asyncio
import json
import os
import threading
import time
from threading import Lock

from flask import Flask, Response, request, stream_with_context

app = Flask(__name__)

_online_count = 0
_lock = Lock()

_SSE_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _now() -> int:
    return int(time.time())

def _now() -> int:
    return int(time.time())

def _change_online(delta: int) -> None:
    global _online_count
    with _lock:
        _online_count = max(0, _online_count + delta)


def _get_online() -> int:
    with _lock:
        return _online_count


def _sse_response(iterable, status: int = 200) -> Response:
    response = Response(iterable, status=status)
    for key, value in _SSE_HEADERS.items():
        response.headers[key] = value
    return response

def _change_online(delta: int) -> None:
    global _online_count
    with _lock:
        _online_count = max(0, _online_count + delta)

@app.after_request
def add_cors_headers(resp: Response) -> Response:
    resp.headers["Access-Control-Allow-Origin"] = "https://solar-system-82998.bubbleapps.io"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Vary"] = "Origin"
    return resp

@app.get("/healthz")
def healthz():
    return {"ok": True}, 200


@app.get("/readyz")
def readyz():
    return {"ok": True}, 200


@app.route("/sse/online", methods=["GET", "OPTIONS"])
def sse_online():
    if request.method == "OPTIONS":
        return Response("", status=204)

    role = request.args.get("role", "client")
    counted = role == "client"

    try:
        if counted:
            _change_online(1)

        def event_stream():
            try:
                while True:
                    payload = {"ts": _now(), "online_total": _get_online()}
                    yield f"data: {json.dumps(payload)}\n\n"
                    time.sleep(2)
            except Exception as exc:  # pragma: no cover - defensive streaming guard
                app.logger.exception("Unhandled SSE streaming error", exc_info=exc)
                error_payload = {
                    "ts": _now(),
                    "online_total": _get_online(),
                    "error": "internal_error",
                }
                yield f"data: {json.dumps(error_payload)}\n\n"
                return
            finally:
                if counted:
                    _change_online(-1)

        return _sse_response(stream_with_context(event_stream()))
    except Exception as exc:  # pragma: no cover - defensive route guard
        app.logger.exception("Unhandled SSE request error", exc_info=exc)

        if counted:
            _change_online(-1)

        def error_stream():
            error_payload = {
                "ts": _now(),
                "online_total": _get_online(),
                "error": "internal_error",
            }
            yield f"data: {json.dumps(error_payload)}\n\n"

        return _sse_response(error_stream())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
