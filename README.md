# Cloud Run Real-time Presence Service

Flask application that records page presence events in Redis and exposes an SSE endpoint for real-time online counts.

## Endpoints

- `POST /v1/hit` — accepts `sid`, `path`, `kind` (load/beat/unload) and stores presence data in Redis.
- `GET /sse/online` — streams aggregated online counts every two seconds via Server-Sent Events. Responses disable proxy buffering so the first event is delivered immediately.
- `GET /healthz` — always returns `{ "ok": true }`.
- `GET /readyz` — returns `{ "ok": true }` when Redis responds to `PING`.

## Environment Variables

- `REDIS_HOST` (required for production)
- `REDIS_PORT` (default: `6379`)
- `REDIS_PASSWORD` (optional)
- `PRESENCE_TTL` (default: `90` seconds)
- `CORS_ORIGINS` — comma separated list of allowed origins (for example `https://solar-system-82998.bubbleapps.io`).
- `PORT` (default: `8080`)

## Development

Install dependencies and run the Flask app:

```bash
pip install -r requirements.txt
python app.py
```

Ensure Redis is available locally when running the server.

## Container Image

To build and run the service in a container (e.g. for Cloud Run), use the provided
`Dockerfile`:

```bash
docker build -t presence-service .
docker run --rm -p 8080:8080 \
  -e REDIS_HOST=host.docker.internal \
  presence-service
```

The container entrypoint uses Gunicorn with the threaded worker class so
Server-Sent Event streams flush promptly while still supporting concurrent
requests.
