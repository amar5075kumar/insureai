# Library Contents Claim Agent

```
   ██████╗ ██████╗ ███████╗███╗   ███╗ ██████╗      █████╗ ██╗
  ██╔════╝██╔═══██╗╚══███╔╝████╗ ████║██╔═══██╗    ██╔══██╗██║
  ██║     ██║   ██║  ███╔╝ ██╔████╔██║██║   ██║    ███████║██║
  ██║     ██║   ██║ ███╔╝  ██║╚██╔╝██║██║   ██║    ██╔══██║██║
  ╚██████╗╚██████╔╝███████╗██║ ╚═╝ ██║╚██████╔╝    ██║  ██║██║
   ╚═════╝ ╚═════╝ ╚══════╝╚═╝     ╚═╝ ╚═════╝     ╚═╝  ╚═╝╚═╝
         📚  Point. Sweep. Claim.  —  InsureAI Library Agent
```

An AI insurance claim agent that inventories a home library by camera.
Point a phone or webcam at a bookshelf. The agent detects every spine, reads
the title, looks up the ISBN, prices the book, and talks you through the sweep
in real time. When you're done, it hands you a priced claim packet ZIP.

---

## What it does

InsureAI turns a live camera feed into a complete, priced inventory of every
book on a shelf — no barcode scanner, no manual typing, no GPU required for
local development. A YOLOv8 ONNX detector finds spines in each frame, Claude
Haiku vision OCRs the text, Open Library resolves the ISBN, and Google Books
supplies a replacement-cost estimate. A LangGraph conversation agent guides
the user by voice or text and, at the end of the sweep, writes a structured
claim packet ready to file. Supports multilingual spines (English, Hindi
Devanagari, Bengali, Gujarati, Tamil, Arabic, and more).

```
┌─────────────────────────────────────────────────────────────┐
│  frontend on http://localhost:3000                          │
│                                                             │
│   📷 live camera          💬 agent chat                     │
│   ┌──────────────┐        Agent: "I see 14 spines so far.   │
│   │  ████ ████   │        Keep panning slowly to the        │
│   │  ████ ████   │        right — I need a clearer look     │
│   │  ████ ████   │        at the bottom row."               │
│   └──────────────┘                                          │
│   Inventory  14 books  ·  est. GBP 428  ·  3 unidentified  │
│   [Vision 74%▓▓▓░] [OCR 80%▓▓▓▓]  · GBP 28.82 / book      │
└─────────────────────────────────────────────────────────────┘
```

---

## Architecture

Ten services. One Redis stream. One LangGraph. Frames flow left-to-right;
conversation state flows right-to-left over WebSocket.

```
 ┌──────────┐  JPEG every 3s      ┌──────────────┐
 │ Browser  │ ──POST /webhooks──► │   backend    │ ──XADD frames:{id}──►┐
 │ :3000    │  /frame             │   FastAPI    │                      │
 │ React    │                     │   :8000      │                      ▼
 │ Vite     │ ◄── WebSocket ──────┤  WS relay    │            ┌─────────────────┐
 │ nginx    │  agent_text         │  SUBSCRIBE   │            │  Redis Stream   │
 └────┬─────┘  inventory_update   │  agent_resp  │            │  frames:{id}    │
      │        sweep_complete     │  ws_broadcast│            │  :6379          │
      │                           └──────┬───────┘            └────────┬────────┘
      │                                  │                             │ XREAD
      │                                  │                             ▼
      │                                  │                  ┌──────────────────┐
      │  user_text / voice               │                  │     vision       │
      │  WebSocket ──────────────────────┤                  │  ONNX YOLOv8n    │
      │                                  │                  │  BookTracker     │
      │                                  │                  │  INSERT books    │
      │                                  │                  └────────┬─────────┘
      │                                  │                           │ Celery
      │                                  │                           ▼
      │                                  │                  ┌──────────────────┐
      │                                  │                  │  worker-lite     │
      │                                  │                  │  Claude Haiku    │
      │                                  │                  │  Open Library    │
      │                                  │                  │  Google Books    │
      │                                  │                  └────────┬─────────┘
      │                                  ▼                           │ UPDATE
      │                       ┌─────────────────┐          ┌─────────────────┐
      │                       │     agents      │          │   postgres      │
      │                       │  LangGraph      │          │   :5432         │
      │                       │  conversation + │          │  books, sweeps  │
      │                       │  sweep orch.    │          └─────────────────┘
      │                       └────────┬────────┘
      │                                │
      │  idle → process_transcript → conversation_agent (Claude Haiku)
      │       → speak → PUBLISH agent_response:{id}
      │  idle → sweep_end → dispatch_workers → wait_workers
      │       → review_agent → deliver_summary (claim_packet.zip)
      │       → idle (post-sweep chat continues)
      │
      │   Optional (cloud / GPU only):
      │   ┌──────────┐  ┌─────────────────────────────────────────────┐
      │   │ livekit  │  │  workers (production, 3.5 GB each)          │
      │   │ :7880    │  │  worker-book-id · worker-pricing             │
      │   │ WebRTC   │  │  worker-measurement                         │
      │   └──────────┘  │  PaddleOCR + PyTorch + Depth Anything v2    │
                        └─────────────────────────────────────────────┘
```

**Local path (`docker-compose.local.yml`, 7 services):** browser →
backend → Redis stream → vision (ONNX CPU) → worker-lite (Claude Haiku +
Google Books) → Postgres. LiveKit and heavy PyTorch workers stay off the
laptop.

**Production path (`docker-compose.yml`, 10 services):** swaps in
LiveKit WebRTC, PaddleOCR (`worker-book-id`), AbeBooks
(`worker-pricing`), Depth Anything v2 (`worker-measurement`), and
GPU-accelerated YOLO.

---

## Prerequisites

| Tool | Version | Why |
|------|---------|-----|
| Docker Engine | 24+ | Every service is a container |
| Docker Compose | v2 (`docker compose`) | Multi-service orchestration |
| Make | any | Thin wrapper around compose/build scripts |
| Node.js | 20 LTS | Only to build frontend outside Docker |
| Python | 3.12 | Only to run agents/workers on the host directly |
| Anthropic API key | `sk-ant-…` | Default LLM + OCR path (slow profile) |

A GPU is **not** required. The `slow` profile runs YOLOv8n on CPU via ONNX
Runtime (~50ms/frame) and sends spine crops to Claude Haiku over the network.

RAM: **8 GB** free for the local 7-service stack. The full 10-service
production stack with heavy workers wants **24 GB+** and a CUDA GPU.

---

## Quick Start

Five steps from a cold clone to a live sweep:

```bash
# 1. Clone
git clone https://github.com/amar5075kumar/insureai.git
cd insureai/library-claim-agent

# 2. Configure
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY and POSTGRES_PASSWORD

# 3. Build the minimal local stack (~5-10 min, vision downloads yolov8n.onnx)
./scripts/build-local.sh

# 4. Start
docker compose -f docker-compose.local.yml up -d

# 5. Open
open http://localhost:3000
```

Or using Make:

```bash
make local-up     # build + start the 7-service local stack
make health       # confirm all services are healthy
make local-down   # stop everything
```

Point the camera at a bookshelf, say "start" or type in the chat, and pan
slowly left-to-right. The inventory fills in real time. Click **Done** when
finished; the agent reviews everything and generates the claim packet. Click
**⬇ Download Packet** to get the ZIP.

---

## Configuration

Copy `.env.example` to `.env`. All services read from the same file.

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `POSTGRES_USER` | `claim_user` | ✓ | Database role |
| `POSTGRES_PASSWORD` | *(set strong)* | ✓ | Role password |
| `POSTGRES_DB` | `library_claim` | ✓ | Database name |
| `LIVEKIT_API_KEY` | `devkey` | cloud | LiveKit key (local mode doesn't use it) |
| `LIVEKIT_API_SECRET` | *(32+ chars)* | cloud | LiveKit HMAC secret |
| `ANTHROPIC_API_KEY` | `sk-ant-…` | slow profile | Direct Anthropic key **or** bearer token for Enterprise Gateway |
| `LLM_PROVIDER` | `anthropic` | ✓ | `anthropic` \| `bedrock` \| `openai` |
| `SWEEP_PROFILE` | `slow` | ✓ | `slow` \| `standard` \| `hot` |
| `BEDROCK_BASE_URL` | — | bedrock | `https://ai-gateway.example.com/bedrock` |
| `BEDROCK_MODEL` | — | bedrock | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `BEDROCK_AUTH_TYPE` | `bearer` | bedrock | `bearer` (Enterprise Gateway) or `aws` (SigV4/IAM) |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | no | Anthropic model to use |
| `OPENAI_API_KEY` | — | openai | Required when `LLM_PROVIDER=openai` |
| `OPENAI_MODEL` | `gpt-4o-mini` | no | OpenAI model |
| `AWS_REGION` | `us-east-1` | bedrock+aws | Region for SigV4 signing |
| `CONV_LLM_OVERRIDE` | — | no | Override conversation model without changing profile |
| `YOLO_DEVICE_OVERRIDE` | — | no | Force `cpu` or `cuda` |
| `CAMERA_MODE` | `direct` | no | `direct` (getUserMedia) or `livekit` (WebRTC) |

**Enterprise Gateway (Bedrock-compatible) example:**

```bash
LLM_PROVIDER=bedrock
BEDROCK_BASE_URL=https://ai-gateway.example.com/bedrock
BEDROCK_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
BEDROCK_AUTH_TYPE=bearer
ANTHROPIC_API_KEY=<your-gateway-bearer-token>
```

The provider can also be chosen at runtime from the frontend **⚙ Configure
AI Provider** panel; choices are saved in `localStorage` and override `.env`
for that browser session only.

---

## Sweep Profiles

Profiles live in `config/sweep_profiles.py` and control which detector
weights, OCR engine, and LLM each worker loads.

| Profile | Use case | YOLO | OCR | LLM | GPU |
|---------|----------|------|-----|-----|-----|
| `slow` | Laptop, WSL2, CI, no GPU | yolov8n ONNX, CPU | Claude Haiku vision API | Claude Haiku | None |
| `standard` | GPU workstation | yolov8s, CUDA | CPU PaddleOCR | Ollama `llama3.1:8b` | Required |
| `hot` | Production GPU server | yolov8m, CUDA | CUDA PaddleOCR | Ollama `llama3.1:70b` | Required |

**Choosing a profile:**

- **`slow`** — first clone, demo, WSL2, or any machine without NVIDIA. Vision
  stays in the 300 MB ONNX image; OCR and pricing stay in the 350 MB
  `worker-lite` image. You pay Anthropic per spine crop and conversational
  turn. This is what `docker-compose.local.yml` is wired for.

- **`standard`** — single consumer GPU. Switch to the full compose file, pull
  `llama3.1:8b` into Ollama, and set `YOLO_DEVICE_OVERRIDE=cuda`.

- **`hot`** — multi-GPU claim-processing server. Swaps in `worker-book-id`
  (PaddleOCR), `worker-pricing` (AbeBooks), and `worker-measurement` (Depth
  Anything v2). Each heavy worker image is ~3.5 GB.

Mix profiles using per-component overrides: keep `SWEEP_PROFILE=slow` but
add `CONV_LLM_OVERRIDE=claude-sonnet-4-6` or `YOLO_DEVICE_OVERRIDE=cuda`.

---

## Local Dev Workflow

Day-to-day you need four commands:

```bash
make local-up      # build + start the 7-service local stack
make local-logs    # tail all containers
make health        # confirm all services healthy
make local-down    # stop everything (data preserved in volumes)
```

`local-*` targets always use `docker-compose.local.yml`. `make start` /
`make stop` / `make logs` target the full production `docker-compose.yml`.
Don't mix them.

### All make targets

| Target | What it does |
|--------|-------------|
| `make local-up` | Build + start 7-service local stack |
| `make local-down` | Stop local stack (volumes kept) |
| `make local-logs` | Tail all local stack containers |
| `make setup` | First-time: copy `.env.example` → `.env` |
| `make pull` | `docker compose pull` — refresh base images |
| `make build` | `docker compose build` — rebuild all images |
| `make start` | Start full 10-service production stack |
| `make stop` | Stop full stack |
| `make restart` | Stop then start |
| `make logs` | Tail full stack (`--tail=100`) |
| `make health` | GET /health + docker compose ps |
| `make disk` | Image/volume disk usage |
| `make clean` | Stop + remove this project's images + volumes |
| `make clean-all` | Same + remove base images (full fresh start) |
| `make shell` | bash in the backend container |
| `make shell-db` | psql in the postgres container |
| `make test` | pytest tests/ |

### Service-specific logs

```bash
docker compose -f docker-compose.local.yml logs -f agents
docker compose -f docker-compose.local.yml logs -f vision
docker compose -f docker-compose.local.yml logs -f worker-lite
docker compose -f docker-compose.local.yml logs -f backend

# Filter for errors + book identifications only
docker compose -f docker-compose.local.yml logs -f worker-lite 2>&1 \
  | grep -E "Vision|identified|Priced|ERROR"
```

### Connect to the database

```bash
make shell-db
# claim_user=#

# or from host (postgres published on :5432)
psql postgresql://claim_user:<password>@localhost:5432/library_claim
```

Useful queries:

```sql
SELECT id, state, country, currency, captured_at FROM sweeps ORDER BY captured_at DESC LIMIT 5;
SELECT title, author, status, replacement_cost_amount FROM books WHERE sweep_id = '<id>';
```

### Rebuild a single service after code change

Python services bind-mount source and run with `--reload`, so **edits are
live without rebuilding**. Rebuild only when you change a `Dockerfile` or
`requirements.txt`:

```bash
docker compose -f docker-compose.local.yml up -d --build worker-lite
docker compose -f docker-compose.local.yml up -d --build vision
docker compose -f docker-compose.local.yml up -d --build frontend
```

### Hot-patch (no rebuild)

Copy a patched file into a running container:

```bash
docker cp services/agents/nodes.py library-claim-agent-agents-1:/app/nodes.py
docker compose -f docker-compose.local.yml restart agents
```

The services auto-reload within 1–2 seconds. Used during development to test
prompt changes and routing logic without a full image rebuild.

---

## Moving to Cloud / GPU

Local uses CPU + APIs + heuristics. Cloud/GPU uses local models + CUDA +
LiveKit. The application code doesn't change — only the compose file, three
worker images, and a handful of env vars.

**Use `docker-compose.yml` on a GPU box.** It defines `livekit`,
`worker-book-id`, `worker-pricing`, `worker-measurement`.

### Component swap table

| Component | Local (slow) | Cloud / GPU config | What to change |
|-----------|-------------|-------------------|----------------|
| Compose file | `docker-compose.local.yml` | `docker-compose.yml` | `make start` instead of `make local-up` |
| LLM | Claude Haiku API | Ollama `llama3.1:8b` or `70b` | `LLM_PROVIDER=` env (see llm_factory.py) |
| OCR / book-ID | worker-lite + Claude vision | worker-book-id + PaddleOCR GPU | Stop `worker-lite`, start `worker-book-id` |
| Vision detector | yolov8n ONNX, CPU | yolov8s/m, CUDA | `YOLO_DEVICE_OVERRIDE=cuda`, mount `.pt` weights |
| Camera mode | getUserMedia browser | LiveKit WebRTC SFU | `CAMERA_MODE=livekit`, run livekit service |
| Frame storage | Local filesystem | MinIO / S3 | Swap `output/frame_store.py`, set `S3_*` vars |
| Pricing | Google Books estimate | AbeBooks scraper | Start `worker-pricing` |
| Room measurement | Frame-count heuristic | Depth Anything v2 | Start `worker-measurement` |
| Sweep profile | `slow` | `standard` or `hot` | `SWEEP_PROFILE=hot` |

### Typical GPU bring-up

```bash
# Verify NVIDIA Container Toolkit is installed
nvidia-smi

# Configure
cp .env.example .env
# edit .env:
#   LLM_PROVIDER=anthropic  (or bedrock/openai)
#   SWEEP_PROFILE=standard
#   YOLO_DEVICE_OVERRIDE=cuda
#   CAMERA_MODE=livekit     (if using WebRTC)

# Build + start full stack
make build
make start
make health

# Pull a local model for the standard profile
docker compose exec ollama ollama pull llama3.1:8b

# Verify CUDA inside vision worker
docker compose exec vision python -c "import onnxruntime as ort; print(ort.get_device())"
```

### LLM: switch to Ollama

```bash
# .env
LLM_PROVIDER=ollama
# Ollama running on the host or as a sidecar:
OLLAMA_BASE_URL=http://host.docker.internal:11434
ANTHROPIC_MODEL=llama3.1:8b   # mapped to the Ollama endpoint

# Pull model on host
ollama pull llama3.1:8b
```

`services/agents/llm_factory.py` handles provider selection. To add a new
provider, add a branch in `build_llm()`.

### Camera: switch to LiveKit

```bash
# .env
CAMERA_MODE=livekit
LIVEKIT_API_KEY=your-key
LIVEKIT_API_SECRET=your-32-char-secret
LIVEKIT_URL=ws://livekit:7880
```

Then rebuild the frontend (VITE vars are baked in at build time):

```bash
docker compose up -d --build frontend
```

The browser switches from `getUserMedia` to the LiveKit client SDK
automatically when `VITE_CAMERA_MODE=livekit`.

### Storage: switch to MinIO / S3

The `output/frame_store.py` module has three functions: `exists()`, `get()`,
`save()`. Swap their bodies to use `aioboto3`:

```python
# output/frame_store.py
import aioboto3, os

ENDPOINT = os.environ.get("S3_ENDPOINT", "http://minio:9000")
BUCKET   = os.environ.get("S3_BUCKET",   "claim-frames")
ACCESS   = os.environ.get("S3_ACCESS_KEY")
SECRET   = os.environ.get("S3_SECRET_KEY")

class FrameStore:
    async def save(self, key: str, data: bytes) -> None:
        session = aioboto3.Session()
        async with session.client("s3", endpoint_url=ENDPOINT,
                                  aws_access_key_id=ACCESS,
                                  aws_secret_access_key=SECRET) as s3:
            await s3.put_object(Bucket=BUCKET, Key=key, Body=data)

    async def get(self, key: str) -> bytes | None:
        ...
```

No other file needs to change.

---

## API Reference

Base URL: `http://localhost:8000`. Timestamps are ISO-8601 UTC. UUIDs are strings.

### `GET /health`

```bash
curl -s localhost:8000/health
# {"status":"ok","profile":"slow","version":"0.1.0"}
```

### `GET /sweeps`

List all sweeps with analytics summary (newest first).

```bash
curl -s localhost:8000/sweeps | python3 -m json.tool
```

```json
[
  {
    "sweep_id": "40bc02ba-…",
    "state": "complete",
    "country": "GB",
    "currency": "GBP",
    "total_books": 5,
    "identified_books": 4,
    "total_replacement_value": 94.63,
    "avg_detection_confidence": 0.64,
    "avg_ocr_confidence": 0.68,
    "packet_available": true,
    "packet_url": "/sweeps/40bc02ba-…/packet"
  }
]
```

### `POST /sweeps`

Create a sweep. The agents runner starts a LangGraph within ~1s.

```bash
curl -s -X POST localhost:8000/sweeps \
  -H 'Content-Type: application/json' \
  -d '{"country":"GB","currency":"GBP"}'
```

```json
{"sweep_id":"40bc02ba-…","ws_url":"ws://localhost:8000/ws/40bc02ba-…","state":"initializing","country":"GB","currency":"GBP"}
```

### `GET /sweeps/{id}`

Current state + book/item counts.

```bash
curl -s localhost:8000/sweeps/40bc02ba-…
```

### `POST /sweeps/{id}/end`

End the sweep (triggers post-processing, packet generation).

```bash
curl -s -X POST localhost:8000/sweeps/40bc02ba-…/end
# {"status":"processing"}
```

### `GET /sweeps/{id}/analytics`

Full detail: book table with confidence scores, prices, language, crops.

```bash
curl -s localhost:8000/sweeps/40bc02ba-…/analytics
```

### `GET /sweeps/{id}/packet`

Download the claim packet ZIP (203 KB, contains JSON + spine crops + HTML report).

```bash
curl -s localhost:8000/sweeps/40bc02ba-…/packet -o claim_packet.zip
unzip claim_packet.zip
```

`404` if the packet hasn't been generated yet (call `/end` first).

### `GET /sweeps/{id}/crops/{book_id}`

Serve the spine crop JPEG for a single book (for the frontend thumbnails).

```bash
curl -s localhost:8000/sweeps/40bc02ba-…/crops/06e1e04c-… -o spine.jpg
```

### `WS /ws/{sweep_id}`

Bidirectional WebSocket. Browser → server sends `user_text` / `sweep_end`.
Server → browser sends `agent_text`, `inventory_update`, `processing_progress`,
`sweep_complete`.

```js
const ws = new WebSocket("ws://localhost:8000/ws/40bc02ba-…");

// send a message
ws.send(JSON.stringify({ type: "user_text", text: "How many books?" }));

// receive inventory updates
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.type === "inventory_update") console.log(msg.books);
  if (msg.type === "agent_text")       console.log("Agent:", msg.text);
};
```

### `POST /webhooks/frame`

Ingest a single JPEG frame (used in `direct` camera mode).

```bash
curl -s -X POST localhost:8000/webhooks/frame \
  -F "sweep_id=40bc02ba-…" \
  -F "frame_id=frame_001" \
  -F "timestamp_ms=1000" \
  -F "jpeg_data=@frame.jpg;type=image/jpeg"
# {"queued":true}
```

---

## Project Structure

```
library-claim-agent/
├── Makefile                         # Developer commands
├── docker-compose.yml               # Full 10-service production stack
├── docker-compose.local.yml         # Minimal 7-service local dev stack
├── .env.example                     # All env vars documented with defaults
├── .gitignore                       # Excludes .env, models/, node_modules/
│
├── config/
│   └── sweep_profiles.py            # slow / standard / hot profiles
│
├── output/                          # Claim packet generation
│   ├── packet_builder.py            # DB → packet → ZIP (filesystem save)
│   ├── frame_store.py               # Filesystem adapter (swap for S3)
│   ├── schemas.py                   # Pydantic models: Book, Sweep, Packet
│   ├── compute_totals.py            # Aggregation: replacement cost totals
│   └── validator.py                 # Packet validation rules
│
├── scripts/
│   ├── build-local.sh               # Build the 7 local images in order
│   ├── pull_image.sh                # Retry-loop docker pull
│   └── download_models.sh           # Pull YOLO / depth weights (optional)
│
└── services/
    ├── postgres/
    │   ├── Dockerfile
    │   └── init.sql                 # Schema: sweeps, books, items, frames
    │
    ├── redis/
    │   └── Dockerfile
    │
    ├── livekit/
    │   ├── Dockerfile
    │   └── livekit.yaml             # LiveKit server config
    │
    ├── backend/                     # FastAPI app
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── app/
    │       ├── main.py              # App factory, CORS, lifecycle
    │       ├── config.py            # pydantic Settings from env
    │       ├── database.py          # SQLAlchemy async engine
    │       ├── websocket_manager.py # WebSocket connection registry
    │       └── api/
    │           ├── sweeps.py        # REST endpoints
    │           ├── websocket.py     # /ws/{sweep_id}  ← relay hub
    │           └── webhooks.py      # /webhooks/frame + /webhooks/audio
    │
    ├── agents/                      # LangGraph conversation + sweep orch.
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   ├── agents_runner.py         # main() — listens for sweep_created:*
    │   ├── graph.py                 # StateGraph definition + MemorySaver
    │   ├── nodes.py                 # All node implementations (async)
    │   ├── routing.py               # route_idle(), route_after_speak()
    │   ├── llm_factory.py           # Anthropic / Bedrock / Enterprise Gateway / OpenAI
    │   ├── tools.py                 # LangGraph tools: update_book, exclude_book
    │   └── review.py                # Post-sweep deterministic review logic
    │
    ├── vision/                      # Frame consumer + ONNX detector
    │   ├── Dockerfile               # Multi-stage: export ONNX → lean runtime
    │   ├── requirements.txt         # onnxruntime, opencv-headless (no torch!)
    │   ├── vision_worker.py         # main() — XREAD → detect → INSERT → Celery
    │   ├── detector.py              # BookDetector + ItemDetector (ONNX Runtime)
    │   ├── book_tracker.py          # 2D spatial deduplication across frames
    │   ├── quality.py               # Blur / glare / motion assessor
    │   └── depth_estimator.py       # Depth Anything v2 stub (inactive in slow)
    │
    ├── worker-lite/                 # Celery workers: OCR + pricing (no GPU)
    │   ├── Dockerfile               # python:3.12-slim + uv, ~350 MB
    │   ├── requirements.txt         # anthropic, httpx, asyncpg, celery
    │   ├── celery_app.py            # broker + backend config
    │   ├── book_id_task.py          # Claude Haiku vision → title/author/lang
    │   ├── pricing_task.py          # Google Books → replacement cost
    │   ├── measurement_task.py      # Frame-count heuristic
    │   └── ws_notify.py             # Push book updates to WebSocket after writes
    │
    ├── workers/                     # Heavy Celery workers (production / GPU)
    │   ├── Dockerfile               # 3.5 GB each (torch + PaddleOCR)
    │   ├── celery_app.py
    │   ├── book_id/
    │   │   ├── worker.py            # PaddleOCR + Open Library + Google Books
    │   │   ├── ocr_processor.py
    │   │   ├── openlibrary.py
    │   │   └── confidence.py
    │   ├── pricing/
    │   │   ├── worker.py            # AbeBooks + Google Books aggregator
    │   │   ├── abebooks.py
    │   │   ├── aggregator.py
    │   │   └── currency.py
    │   └── measurement/
    │       ├── worker.py            # Depth Anything v2 room geometry
    │       └── geometry.py
    │
    └── frontend/                    # React + Vite SPA
        ├── Dockerfile               # node:20-alpine build → nginx:alpine serve
        ├── .dockerignore            # excludes node_modules, dist
        ├── package.json
        ├── vite.config.ts
        └── src/
            ├── App.tsx              # Phase router: setup / sweep / analytics
            ├── components/
            │   ├── SetupScreen.tsx  # Landing page (Grok-designed library UI)
            │   ├── SweepRoom.tsx    # Camera + chat + inventory (live sweep)
            │   ├── AgentVoice.tsx   # TTS audio playback + agent text
            │   ├── AnalyticsScreen.tsx  # Session history + evidence viewer
            │   └── CompleteScreen.tsx   # Post-sweep results + download
            └── hooks/
                ├── useCamera.ts        # getUserMedia / LiveKit switch
                ├── useDirectCamera.ts  # getUserMedia + Web Speech API (STT)
                ├── useInventory.ts     # WebSocket → book/item state
                └── useWebSocket.ts     # Shared singleton WS per sweepId
```

---

## Contributing

Three stable extension points. Each is a single file with a known
function signature — add a provider without touching the pipeline.

### New LLM provider

`services/agents/llm_factory.py` — `build_llm()` returns a LangChain
`BaseChatModel`. The file already supports Anthropic, Bedrock/Enterprise Gateway,
and OpenAI. To add another:

```python
# llm_factory.py
def build_llm(max_tokens: int = 150, temperature: float = 0.3):
    if LLM_PROVIDER == "my_provider":
        return _build_my_provider(max_tokens, temperature)
    ...

def _build_my_provider(max_tokens, temperature):
    from langchain_my_provider import ChatMyProvider
    return ChatMyProvider(api_key=os.environ["MY_API_KEY"], ...)
```

Add `MY_API_KEY` and `LLM_PROVIDER=my_provider` to `.env.example`.
The frontend ⚙ panel will automatically display it as a radio option.

### New OCR engine

`services/worker-lite/book_id_task.py` — `_identify_with_claude()` is the
single function that receives a JPEG crop as `bytes` and returns
`{"title": str, "author": str, "language": str}`. To swap OCR:

```python
def _identify_with_new_engine(image_bytes: bytes) -> dict:
    # load your model, run inference, return same shape
    return {"title": "...", "author": "...", "language": "en"}
```

For a GPU engine (PaddleOCR, EasyOCR with CUDA), **don't put it in
`worker-lite`**. Add `services/workers/<name>/` + a new Dockerfile and
consume the same `book_id` Celery queue. Stop `worker-lite`, start your
worker. The rest of the pipeline is unaffected.

### New pricing source

`services/worker-lite/pricing_task.py` — `_fetch_google_books_price(isbn, title)`
returns `{"amount": float, "source": str}` or `None`. Replace or chain it:

```python
async def _fetch_my_price_source(isbn, title):
    # hit your API
    return {"amount": 12.99, "source": "my_source"}
```

For a real scraper, add `services/workers/pricing/` and let it consume the
`pricing` Celery queue. Write `replacement_cost_amount` + `replacement_cost_source`
to the `books` table — that's the contract.

### PR checklist

- `./scripts/build-local.sh` completes without error
- `docker compose -f docker-compose.local.yml ps` shows all 7 services healthy
- New env vars documented in `.env.example`
- No secrets committed
- New containers have a healthcheck in the compose file

---

## License

MIT — see `LICENSE`.

---

*Built with [LangGraph](https://github.com/langchain-ai/langgraph), [YOLOv8](https://github.com/ultralytics/ultralytics), [Claude Haiku](https://www.anthropic.com/claude), [FastAPI](https://fastapi.tiangolo.com), and [React](https://react.dev).*
