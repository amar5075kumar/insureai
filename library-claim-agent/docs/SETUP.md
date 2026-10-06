# Setup & Configuration

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Docker Engine | 24+ | All services run in containers |
| Docker Compose | v2 (`docker compose`) | |
| Make | any | Thin wrapper around compose |
| Anthropic API key | — | For `slow` profile (default) |

**No GPU required** for the default `slow` profile.

---

## Installation

```bash
git clone https://github.com/amar5075kumar/insureai.git
cd insureai/library-claim-agent

cp .env.example .env
# Edit .env — minimum: set ANTHROPIC_API_KEY and POSTGRES_PASSWORD

./scripts/build-local.sh
docker compose -f docker-compose.local.yml up -d
```

First build takes ~8 minutes (vision service downloads and exports yolov8n.onnx).
Subsequent builds use cached layers and take ~30 seconds.

---

## Environment Variables

All services read from `.env` in the project root. Copy `.env.example` to get started.

### Required

| Variable | Example | Description |
|----------|---------|-------------|
| `POSTGRES_PASSWORD` | `str0ngP@ss` | Database password (min 16 chars recommended) |
| `POSTGRES_USER` | `claim_user` | Database role (default works) |
| `POSTGRES_DB` | `library_claim` | Database name |
| `ANTHROPIC_API_KEY` | `sk-ant-…` | Required for `slow` profile (default) |

### LLM Provider

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `anthropic` | `anthropic` \| `bedrock` \| `openai` |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Model name |
| `OPENAI_API_KEY` | — | Required when `LLM_PROVIDER=openai` |
| `OPENAI_MODEL` | `gpt-4o-mini` | |
| `BEDROCK_BASE_URL` | — | Bedrock-compatible gateway URL |
| `BEDROCK_MODEL` | — | e.g. `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `BEDROCK_AUTH_TYPE` | `bearer` | `bearer` (token auth) or `aws` (SigV4) |

### Sweep & Camera

| Variable | Default | Description |
|----------|---------|-------------|
| `SWEEP_PROFILE` | `slow` | `slow` \| `standard` \| `hot` — see [Cloud & GPU](CLOUD.md) |
| `CAMERA_MODE` | `direct` | `direct` (getUserMedia) or `livekit` (WebRTC) |
| `LIVEKIT_API_KEY` | `devkey` | Only needed when `CAMERA_MODE=livekit` |
| `LIVEKIT_API_SECRET` | — | Min 32 chars — only for LiveKit mode |

### Per-component overrides

```bash
CONV_LLM_OVERRIDE=claude-sonnet-4-6   # override conversation model only
YOLO_DEVICE_OVERRIDE=cuda              # force GPU for vision
```

### Enterprise Gateway (Bedrock-compatible)

```bash
LLM_PROVIDER=bedrock
BEDROCK_BASE_URL=https://your-gateway.example.com/bedrock
BEDROCK_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
BEDROCK_AUTH_TYPE=bearer
ANTHROPIC_API_KEY=<bearer-token>
```

---

## Make Targets

### Local dev stack (7 services, no GPU)

```bash
make local-up        # build + start local stack
make local-down      # stop (data preserved in volumes)
make local-logs      # tail all containers
make local-health    # check backend / postgres / redis / frontend
make local-restart   # local-down then local-up
```

### Full production stack (10 services)

```bash
make setup           # first-time: pull + build + start
make start           # start all 10 services
make stop            # stop
make restart         # stop + start
make logs            # tail all containers
make health          # service health check
```

### Utilities

```bash
make shell           # bash in backend container
make shell-db        # psql in postgres container
make disk            # docker image/volume disk usage
make clean           # stop + remove this project's images
make clean-all       # clean + remove base images (full reset)
```

### GPU / Production (Makefile.cloud)

```bash
make -f Makefile.cloud setup          # GPU verify + build + Ollama pull
make -f Makefile.cloud verify-gpu     # check nvidia-smi + Docker GPU
make -f Makefile.cloud pull-ollama-8b # pull llama3.1:8b
make -f Makefile.cloud backup-db      # pg_dump to backups/
```

---

## Ports

| Service | Port | URL |
|---------|------|-----|
| Frontend | 3000 | http://localhost:3000 |
| Backend API | 8000 | http://localhost:8000/health |
| PostgreSQL | 5432 | `psql postgresql://claim_user:<pass>@localhost:5432/library_claim` |
| Redis | 6379 | `redis-cli -p 6379` |
| LiveKit | 7880 | Cloud/WebRTC mode only |

---

## Rebuilding after code changes

Python services use `--reload` so **edits are live without rebuilding**.
Rebuild only when `Dockerfile` or `requirements.txt` changes:

```bash
docker compose -f docker-compose.local.yml up -d --build worker-lite
docker compose -f docker-compose.local.yml up -d --build vision
docker compose -f docker-compose.local.yml up -d --build backend
```

Frontend (Vite HMR covers source edits; rebuild after `package.json` changes):
```bash
docker compose -f docker-compose.local.yml up -d --build frontend
```
