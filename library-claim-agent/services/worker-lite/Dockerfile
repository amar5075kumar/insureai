FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir uv && uv pip install --system --no-cache -r requirements.txt

COPY . .

CMD ["celery", "-A", "celery_app", "worker", \
     "-Q", "book_id,pricing,measurement", \
     "-c", "4", "--loglevel=info", \
     "-n", "worker-lite@%h"]
