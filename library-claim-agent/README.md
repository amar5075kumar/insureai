# InsureAI — Library Contents Claim Agent

```
  ██╗███╗   ██╗███████╗██╗   ██╗██████╗ ███████╗ █████╗ ██╗
  ██║████╗  ██║██╔════╝██║   ██║██╔══██╗██╔════╝██╔══██╗██║
  ██║██╔██╗ ██║███████╗██║   ██║██████╔╝█████╗  ███████║██║
  ██║██║╚██╗██║╚════██║██║   ██║██╔══██╗██╔══╝  ██╔══██║██║
  ██║██║ ╚████║███████║╚██████╔╝██║  ██║███████╗██║  ██║██║
  ╚═╝╚═╝  ╚═══╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝
           📚  Point. Sweep. Claim.  —  InsureAI Library Agent
```

> Point a phone camera at a bookshelf. Get a priced insurance claim packet.

An AI agent that inventories a home library by camera — detecting spines, reading titles, looking up ISBNs, pricing books, and guiding the user through a live sweep by voice or text. No GPU required to run locally.

---

## What it does

```
📷 Camera → YOLOv8 detects spines → Claude reads text → Open Library finds ISBN
→ Google Books prices it → LangGraph agent guides the user → Claim packet ZIP
```

- **Live camera sweep** — frames sent every 3 seconds, books appear in real time
- **Multilingual OCR** — English, Hindi, Bengali, Gujarati, Tamil, Arabic and more
- **Voice + text chat** — Web Speech API STT, agent responds via text
- **Confidence scores** — Vision % (YOLO) and OCR % (Claude) per book
- **Analytics history** — all past sessions with book tables and evidence download
- **No GPU needed** — local dev runs on CPU with ONNX and Claude Haiku API

---

## Quick Start

```bash
git clone https://github.com/amar5075kumar/insureai.git
cd insureai/library-claim-agent

cp .env.example .env
# Set ANTHROPIC_API_KEY and POSTGRES_PASSWORD in .env

./scripts/build-local.sh          # builds 7 images (~8 min first time)
docker compose -f docker-compose.local.yml up -d

open http://localhost:3000
```

Or with Make:

```bash
make local-up     # build + start
make local-health # check all services
make local-down   # stop
```

---

## Documentation

| Guide | Description |
|-------|-------------|
| [Setup & Configuration](docs/SETUP.md) | Installation, `.env` variables, all make targets |
| [Architecture](docs/ARCHITECTURE.md) | How the 10 services connect, data flow, design decisions |
| [API Reference](docs/API.md) | REST endpoints, WebSocket protocol, curl examples |
| [Cloud & GPU](docs/CLOUD.md) | Switching from local CPU to production GPU stack |
| [Contributing](docs/CONTRIBUTING.md) | Adding LLM providers, OCR engines, pricing sources |

---

## Services at a glance

| Service | Port | Role |
|---------|------|------|
| frontend | 3000 | React UI — camera + chat + inventory |
| backend | 8000 | FastAPI REST + WebSocket relay |
| agents | — | LangGraph conversation + sweep orchestration |
| vision | — | ONNX YOLOv8n frame consumer (300 MB, no GPU) |
| worker-lite | — | Claude OCR + Google Books pricing (350 MB, no GPU) |
| postgres | 5432 | Persistent data |
| redis | 6379 | Pub/sub, streams, task queues |

---

## License

MIT
