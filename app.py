import json
import logging
import os
import threading
import time
from typing import Iterable

from flask import Flask, Response, jsonify, request, stream_with_context


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

raw_origins = os.environ.get("CORS_ORIGINS", "*")
allowed_origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
allow_any_origin = "*" in allowed_origins or not allowed_origins

_online_count = 0
_online_count_lock = threading.Lock()


def _increment_online_count() -> int:
    global _online_count
    with _online_count_lock:
        _online_count += 1
        return _online_count


def _decrement_online_count() -> int:
    global _online_count
    with _online_count_lock:
        _online_count = max(0, _online_count - 1)
        return _online_count


def _get_online_count() -> int:
    with _online_count_lock:
        return _online_count


def _make_cors_preflight_response() -> Response:
    """Return a CORS-compliant response for browser preflight checks."""

    response = Response(status=204)
    return response


def _resolve_allow_origin(origin: str | None) -> tuple[str | None, bool]:
    """Determine the appropriate Access-Control-Allow-Origin header value."""

    if allow_any_origin:
        if origin:
            return origin, True
        return "*", True
    if origin and origin in allowed_origins:
        return origin, True
    if allowed_origins:
        return allowed_origins[0], True
    return "*", True


@app.after_request
def apply_cors(response: Response) -> Response:
    origin = request.headers.get("Origin")
    allow_origin, should_vary = _resolve_allow_origin(origin)

    response.headers["Access-Control-Allow-Origin"] = allow_origin or "*"
    if allow_origin != "*":
        response.headers["Access-Control-Allow-Credentials"] = "true"

    if should_vary:
        existing_vary = response.headers.get("Vary")
        if existing_vary:
            if "Origin" not in existing_vary:
                response.headers["Vary"] = f"{existing_vary}, Origin"
        else:
            response.headers["Vary"] = "Origin"
    else:
        response.headers.setdefault("Vary", "Origin")

    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Max-Age"] = "600"
    return response


def _sse_stream() -> Iterable[str]:
    current = _increment_online_count()
    logger.info("sse_connect total=%s", current)
    try:
        while True:
            payload = {"ts": int(time.time()), "online_total": _get_online_count()}
            data = json.dumps(payload, ensure_ascii=False)
            yield f"data: {data}\n\n"
            time.sleep(2)
    finally:
        current = _decrement_online_count()
        logger.info("sse_disconnect remaining=%s", current)


@app.route("/sse/online", methods=["GET", "OPTIONS"])
def stream_online() -> Response:
    if request.method == "OPTIONS":
        return _make_cors_preflight_response()
    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return Response(
        stream_with_context(_sse_stream()),
        headers=headers,
        mimetype="text/event-stream",
    )


@app.route("/healthz", methods=["GET", "HEAD"])
def healthz() -> Response:
    return jsonify({"ok": True})


@app.route("/readyz", methods=["GET", "HEAD"])
def readyz() -> Response:
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
