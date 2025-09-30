# Cloud Run Real-time Presence Service

Flask application that records page presence events in Redis and exposes an SSE endpoint for real-time online counts.

## Endpoints

- `POST /v1/hit` — accepts `sid`, `path`, `kind` (load/beat/unload) and stores presence data in Redis. Redis write failures are
  logged with `[HIT_ERR_*]` tags and return `{ "ok": false, "degraded": true }` with HTTP 202 instead of surfacing a 5xx.
- `GET /sse/online` — streams aggregated online counts every two seconds via Server-Sent Events. Responses disable proxy buffering so the first event is delivered immediately.
- `GET /healthz` — always returns `{ "ok": true }`.
- `GET /readyz` — returns `{ "ok": true }` when Redis responds to `PING`.

## Environment Variables

- `REDIS_HOST` (required for production)
- `REDIS_PORT` (default: `6379`)
- `REDIS_PASSWORD` (optional)
- `PRESENCE_TTL` (default: `90` seconds)
- `CORS_ORIGINS` — comma separated list of allowed origins (default: `*`; set to `https://solar-system-82998.bubbleapps.io` once verified).
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

## Troubleshooting

- `/healthz` returning `404` usually means the latest container revision was not
  deployed; confirm the Cloud Run service is using the new image.
- `/readyz` returning `{ "ok": false, "error": "..." }` means the
  application cannot connect to Redis. Verify the `REDIS_HOST`, networking (for
  example, a VPC connector), and that the instance is in the same region.

## Cloud Run Deployment Checklist

1. Confirm traffic is pinned to the latest revision:

   ```bash
   gcloud run services describe online --region asia-northeast1 \
     --format='value(status.url,status.traffic[0].revisionName)'
   ```

   Reassign traffic in the console or with `gcloud` if the active revision does
   not match the latest deployment.

2. Enable private Redis access using Serverless VPC Access and direct all
   egress through it so Memorystore can be reached:

   ```bash
   gcloud run services update online --region asia-northeast1 \
     --vpc-connector <YOUR_VPC_CONNECTOR> --vpc-egress all-traffic
   ```

3. Point the service at the Memorystore instance using its private IP and set
   the runtime tuning variables:

   ```bash
   gcloud run services update online --region asia-northeast1 \
     --set-env-vars \
       REDIS_HOST=<MEMORYSTORE_PRIVATE_IP>,\
       REDIS_PORT=6379,\
       PRESENCE_TTL=90,\
       CORS_ORIGINS=https://solar-system-82998.bubbleapps.io
   ```

4. Reduce cold starts and increase concurrency headroom for SSE connections:

   ```bash
   gcloud run services update online --region asia-northeast1 \
     --min-instances 1 --concurrency 50
   ```
