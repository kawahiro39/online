import json
import logging
import os
import time
from typing import Dict, Iterable, List, Tuple

from flask import Flask, Response, jsonify, request, stream_with_context
import redis


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

redis_host = os.environ.get("REDIS_HOST", "localhost")
redis_port = int(os.environ.get("REDIS_PORT", "6379"))
redis_password = os.environ.get("REDIS_PASSWORD")

_redis_pool = redis.ConnectionPool(
    host=redis_host,
    port=redis_port,
    password=redis_password,
    socket_connect_timeout=1,
    socket_timeout=1,
    health_check_interval=30,
    decode_responses=True,
)


def _create_redis_client() -> redis.Redis:
    """Create a Redis client with aggressive timeouts for probe endpoints."""

    return redis.Redis(
        connection_pool=_redis_pool,
        decode_responses=True,
        retry_on_timeout=True,
    )


def _get_redis_client() -> redis.Redis:
    """Return a Redis client instance bound to the shared connection pool."""

    return _create_redis_client()

presence_ttl = int(os.environ.get("PRESENCE_TTL", "90"))
raw_origins = os.environ.get("CORS_ORIGINS", "*")
allowed_origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
allow_any_origin = "*" in allowed_origins or not allowed_origins


def _make_cors_preflight_response() -> Response:
    """Return a CORS-compliant response for browser preflight checks."""

    response = Response(status=204)
    return response


def _resolve_allow_origin(origin: str | None) -> tuple[str | None, bool]:
    """Determine the appropriate Access-Control-Allow-Origin header value."""

    if allow_any_origin:
        if origin:
            return origin, True
        return "*", False
    if origin and origin in allowed_origins:
        return origin, True
    return None, False


@app.after_request
def apply_cors(response: Response) -> Response:
    origin = request.headers.get("Origin")
    allow_origin, should_vary = _resolve_allow_origin(origin)

    if allow_origin:
        response.headers["Access-Control-Allow-Origin"] = allow_origin
        if allow_origin != "*":
            response.headers["Access-Control-Allow-Credentials"] = "true"
        if should_vary:
            existing_vary = response.headers.get("Vary")
            if existing_vary:
                if "Origin" not in existing_vary:
                    response.headers["Vary"] = f"{existing_vary}, Origin"
            else:
                response.headers["Vary"] = "Origin"

    requested_method = request.headers.get("Access-Control-Request-Method")
    if requested_method:
        response.headers["Access-Control-Allow-Methods"] = requested_method
    else:
        response.headers.setdefault("Access-Control-Allow-Methods", "GET,POST,OPTIONS")

    requested_headers = request.headers.get("Access-Control-Request-Headers")
    if requested_headers:
        response.headers["Access-Control-Allow-Headers"] = requested_headers
    else:
        response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type")
    response.headers.setdefault("Access-Control-Max-Age", "600")
    return response


@app.route("/v1/hit", methods=["POST", "OPTIONS"])
def record_hit() -> Response:
    if request.method == "OPTIONS":
        return _make_cors_preflight_response()

    try:
        payload = request.get_json(force=True)  # type: ignore[no-untyped-call]
    except Exception:  # noqa: BLE001
        logger.exception("hit_error: invalid_json")
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    if not isinstance(payload, dict):
        logger.error("hit_error: payload_not_object")
        return jsonify({"ok": False, "error": "invalid_payload"}), 400

    sid = payload.get("sid")
    path = payload.get("path", "/")
    event_kind = payload.get("kind")

    if not isinstance(sid, str) or not sid.strip():
        logger.error("hit_error: missing_sid")
        return jsonify({"ok": False, "error": "sid_required"}), 400
    sid = sid.strip()

    if not isinstance(path, str) or not path:
        path = "/"

    if event_kind not in {"load", "beat", "unload"}:
        logger.error("hit_error: invalid_kind")
        return jsonify({"ok": False, "error": "invalid_kind"}), 400

    now = int(time.time())
    presence_key = f"presence:{sid}"
    online_key = f"online:{path}"

    redis_client = _get_redis_client()
    pipeline = redis_client.pipeline(transaction=False)
    if event_kind == "unload":
        pipeline.delete(presence_key)
        pipeline.zrem(online_key, sid)
    else:
        pipeline.setex(presence_key, presence_ttl, now)
        pipeline.zadd(online_key, {sid: now})
        if event_kind == "load":
            pipeline.incr("metrics:pv:total")
    pipeline.zremrangebyscore(online_key, 0, now - presence_ttl)
    pipeline.expire(online_key, 300)

    try:
        pipeline.execute()
    except redis.RedisError:  # noqa: BLE001
        logger.exception("hit_error: redis_failure")
        return jsonify({"ok": False, "error": "redis_error"}), 503

    logger.info("hit_ok sid=%s kind=%s path=%s", sid, event_kind, path)
    return jsonify({"ok": True})


def _collect_online_stats() -> Dict[str, object]:
    now = int(time.time())
    cutoff = now - presence_ttl
    total = 0
    per_path: List[Tuple[str, int]] = []

    try:
        redis_client = _get_redis_client()
        for key in redis_client.scan_iter(match="online:*"):
            path = key.split("online:", 1)[1]
            # Clean up stale members to keep counts accurate
            redis_client.zremrangebyscore(key, 0, cutoff)
            count = redis_client.zcard(key)
            if count > 0:
                total += count
                per_path.append((path, count))
    except redis.RedisError:  # noqa: BLE001
        logger.exception("sse_error: redis_failure")
        raise

    per_path.sort(key=lambda item: item[1], reverse=True)
    top_pages = per_path[:10]

    return {
        "ts": now,
        "online_total": total,
        "top_pages": top_pages,
    }


def _sse_stream() -> Iterable[str]:
    while True:
        try:
            payload = _collect_online_stats()
        except redis.RedisError:
            payload = {"ts": int(time.time()), "online_total": 0, "top_pages": []}
        data = json.dumps(payload, ensure_ascii=False)
        yield f"data: {data}\n\n"
        time.sleep(2)


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
    try:
        _get_redis_client().ping()
    except redis.RedisError:
        return jsonify({"ok": False}), 503
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
