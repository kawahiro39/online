FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080

CMD ["gunicorn", "--bind", ":8080", "--workers", "1", "--worker-class", "gthread", "--threads", "8", "--keep-alive", "5", "--timeout", "0", "app:app"]