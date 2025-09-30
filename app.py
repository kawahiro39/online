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

def _create_redis_client() -> redis.Redis:
    return redis.Redis(
        host=redis_host,
        port=redis_port,
        password=redis_password,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        health_check_interval=30,
    )


redis_client = _create_redis_client()

presence_ttl = int(os.environ.get("PRESENCE_TTL", "90"))
allowed_origins = [origin.strip() for origin in os.environ.get("CORS_ORIGINS", "").split(",") if origin.strip()]


def _get_request_origin() -> str | None:
    origin = request.headers.get("Origin")
    if origin and origin in allowed_origins:
        return origin
    return None


@app.after_request
def apply_cors(response: Response) -> Response:
    origin = request.headers.get("Origin")
    if origin and origin in allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        existing_vary = response.headers.get("Vary")
        if existing_vary:
            if "Origin" not in existing_vary:
                response.headers["Vary"] = f"{existing_vary}, Origin"
        else:
            response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


@app.route("/v1/hit", methods=["POST", "OPTIONS"])
def record_hit() -> Response:
    if request.method == "OPTIONS":
        response = app.make_default_options_response()
        origin = _get_request_origin()
        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
        return response

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


@app.route("/sse/online", methods=["GET"])
def stream_online() -> Response:
    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    return Response(stream_with_context(_sse_stream()), headers=headers)


@app.route("/healthz", methods=["GET"])
def healthz() -> Response:
    return jsonify({"ok": True})


@app.route("/readyz", methods=["GET"])
def readyz() -> Response:
    try:
        redis_client.ping()
    except redis.RedisError:
        return jsonify({"ok": False}), 503
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
