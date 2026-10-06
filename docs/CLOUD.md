# Cloud & GPU Setup

Local dev uses CPU + APIs. Production uses local models + CUDA + LiveKit.
The application code doesn't change — only the compose file and env vars.

**Use `docker-compose.yml` on a GPU box** (10 services).
**Use `docker-compose.local.yml` on a laptop** (7 services, no GPU).

---

## Component Swap Table

| Component | Local (`slow`) | Cloud / GPU | Change |
|-----------|---------------|-------------|--------|
| Compose file | `docker-compose.local.yml` | `docker-compose.yml` | `make start` |
| LLM | Claude Haiku API | Ollama `llama3.1:8b/70b` | `LLM_PROVIDER=ollama` |
| OCR | worker-lite + Claude | worker-book-id + PaddleOCR GPU | stop lite, start heavy |
| Vision | yolov8n ONNX, CPU | yolov8s/m, CUDA | `YOLO_DEVICE_OVERRIDE=cuda` |
| Camera | getUserMedia | LiveKit WebRTC | `CAMERA_MODE=livekit` |
| Storage | Filesystem | MinIO / S3 | swap `frame_store.py` |
| Pricing | Google Books estimate | AbeBooks scraper | start `worker-pricing` |
| Room measure | Frame-count heuristic | Depth Anything v2 | start `worker-measurement` |
| Sweep profile | `slow` | `standard` or `hot` | `SWEEP_PROFILE=hot` |

---

## GPU Bring-Up

```bash
# 1. Verify NVIDIA Container Toolkit
nvidia-smi

# 2. Configure
cp .env.example .env
# Edit .env:
#   SWEEP_PROFILE=standard
#   YOLO_DEVICE_OVERRIDE=cuda
#   LLM_PROVIDER=ollama

# 3. Build + start full stack
make build
make start

# 4. Pull a local model
docker compose exec ollama ollama pull llama3.1:8b

# 5. Verify GPU in containers
docker compose exec vision python -c "import onnxruntime as ort; print(ort.get_device())"
```

Or use `Makefile.cloud`:
```bash
make -f Makefile.cloud setup    # GPU verify + build + Ollama pull
```

---

## LLM: Switch to Ollama

```bash
# .env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
ANTHROPIC_MODEL=llama3.1:8b

# Pull the model on the host
ollama pull llama3.1:8b
```

To add a new provider: edit `services/agents/llm_factory.py`, add a branch in `build_llm()`.

---

## Camera: Switch to LiveKit WebRTC

```bash
# .env
CAMERA_MODE=livekit
LIVEKIT_API_KEY=your-key
LIVEKIT_API_SECRET=your-32-char-secret

# Rebuild frontend (VITE_ vars are baked in at build time)
docker compose up -d --build frontend
docker compose up -d livekit
```

---

## Storage: Switch to S3 / MinIO

Replace the 3 methods in `output/frame_store.py`:

```python
class FrameStore:
    async def save(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes | None: ...
    def exists(self, key: str) -> bool: ...
```

Add env vars: `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`.
No other file needs to change.

---

## OCR: Switch to PaddleOCR (GPU)

```bash
# Stop lightweight worker, start heavy worker
docker compose stop worker-lite
docker compose up -d worker-book-id    # PaddleOCR + PyTorch GPU, ~3.5 GB image
```

Both consume the same `book_id` Celery queue — no application code change.

---

## Pricing: Switch to AbeBooks

```bash
docker compose up -d worker-pricing    # AbeBooks scraper, ~3.5 GB image
```

Consumes the same `pricing` Celery queue.

---

## Measurement: Switch to Depth Anything v2

```bash
docker compose up -d worker-measurement   # Depth Anything v2, GPU required
```

Provides accurate room geometry instead of the frame-count heuristic.
