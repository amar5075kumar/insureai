# Architecture

## Overview

Ten Docker services. Frames flow left to right through a Redis stream; conversation flows right to left over WebSocket.

```
 Browser (localhost:3000)
     │
     ├── POST /webhooks/frame (JPEG every 3s)
     │         │
     │         ▼
     │   Backend FastAPI ──XADD──► Redis Stream (frames:{sweep_id})
     │         │                           │
     │         │                           └──XREAD──► Vision Worker
     │         │                                          │ ONNX YOLOv8n
     │         │                                          │ BookTracker (2D dedup)
     │         │                                          │ INSERT books
     │         │                                          │ Celery task
     │         │                                          ▼
     │         │                                   worker-lite
     │         │                                   Claude Haiku OCR
     │         │                                   Open Library ISBN
     │         │                                   Google Books price
     │         │                                   UPDATE books
     │         │                                   PUBLISH ws_broadcast
     │         │
     ├── WebSocket /ws/{sweep_id}
     │         │
     │         ├──► RPUSH transcript_queue / sweep_end_queue
     │         │         │
     │         │         └──► message_pump (BLPOP)
     │         │                   │
     │         │                   └──► LangGraph StateGraph
     │         │                          idle → process_transcript
     │         │                               → conversation_agent (LLM)
     │         │                               → speak
     │         │                               → PUBLISH agent_response
     │         │
     │         ◄── agent_text / inventory_update / sweep_complete
```

---

## Services

| Service | Image size | Role |
|---------|-----------|------|
| **postgres** | 419 MB | Stores sweeps, books, items, frames |
| **redis** | 57 MB | Pub/sub, streams, Celery broker |
| **backend** | 411 MB | FastAPI: REST + WebSocket + frame ingest |
| **agents** | 871 MB | LangGraph: conversation + sweep orchestration |
| **vision** | 721 MB | ONNX YOLOv8n frame consumer |
| **worker-lite** | 359 MB | Claude OCR + pricing (no PyTorch) |
| **frontend** | 95 MB | React/Vite served by nginx |
| **livekit** | 136 MB | WebRTC SFU (cloud mode only) |
| **workers** | 3.46 GB each | PaddleOCR + PyTorch (production only) |

---

## Key Design Decisions

### In-process message queues (not Redis in idle_node)

The LangGraph `idle_node` runs every 150ms. Polling Redis on every iteration caused connection churn and state corruption. Instead:

- `message_pump` coroutine does `BLPOP` on Redis with `timeout=1s`
- Delivers to in-process dicts: `_pending_transcripts`, `_pending_quality`, `_pending_sweep_ends`
- `idle_node` reads from dicts (no I/O, no blocking)

### ONNX Runtime for vision (no PyTorch/CUDA)

- Stage 1 Dockerfile: exports `yolov8n.onnx` using ultralytics (downloads ~2 GB PyTorch)
- Stage 2 Dockerfile: only `onnxruntime` (~50 MB). Final image: 721 MB vs 3.5 GB
- Inference: ~50 ms/frame on CPU, sufficient for 3-second frame intervals

### LangGraph operator.add reducers

`conversation_history` and `celery_task_ids` use `Annotated[List, operator.add]` — lists accumulate across steps. Every node returns **only changed keys**, never `{**state}`. Spreading the full state causes list doubling on every step.

### Shared WebSocket singleton

Both `useInventory` and `AgentVoice` components need the same WebSocket. A module-level `Map<sweepId, SharedSocket>` ensures one physical connection per sweep, reference-counted on mount/unmount.

### Post-sweep chat

After `deliver_summary`, the graph loops back to `idle` (not `END`). The message pump keeps running (doesn't exit on sweep_end). The agent can answer "What is the total?" after the packet is generated.

### Packet storage: filesystem not MinIO

For local dev simplicity, `output/frame_store.py` reads/writes to the shared `frame_data` Docker volume. The backend, vision, agents, and worker-lite all mount the same named volume. Swap `frame_store.py` for S3/MinIO in production — only 3 methods: `exists()`, `get()`, `save()`.

---

## Data Flow: One complete sweep

```
1. User opens http://localhost:3000 → SetupScreen
2. Clicks Start Sweep → POST /sweeps → backend creates row → PUBLISH sweep_created
3. agents picks up sweep_created → starts LangGraph graph + message_pump
4. Browser requests camera → getUserMedia
5. Every 3s: canvas.toBlob → POST /webhooks/frame
6. backend saves JPEG to /app/frame_data → XADD frames:{id}
7. vision XREAD → YOLOv8n detect spines → BookTracker dedup → INSERT books
8. worker-lite Celery task: crop → Claude Haiku → title/author → Open Library ISBN
   → Google Books price → UPDATE books → PUBLISH ws_broadcast (inventory_update)
9. WebSocket relay forwards inventory_update → browser shows book in list
10. User speaks → Web Speech API → sendText(transcript) → WebSocket user_text
    → RPUSH transcript_queue → message_pump BLPOP → deliver_transcript
    → idle_node returns latest_transcript → route_idle → process_transcript
    → conversation_agent (Claude) → speak_node PUBLISH agent_response
    → WebSocket relay → browser shows agent reply
11. User clicks Done → sweep_end_queue → route_idle → dispatch_workers
    → wait_workers (DB poll) → review_agent → deliver_summary
    → claim_packet.zip written to /app/frame_data/{sweep_id}/
    → PUBLISH sweep_complete → browser shows completion banner
12. User downloads packet or starts new sweep
```

---

## Database Schema (key tables)

```sql
sweeps (id, state, country, currency, captured_at, completed_at)
books  (id, sweep_id, status, title, author, isbn,
        id_confidence, detection_confidence,
        replacement_cost_amount, replacement_cost_source,
        detected_language, frame_ref)
items  (id, sweep_id, category, confidence, frame_ref)
frames (id, sweep_id, timestamp_ms)
```

States: `initializing → sweeping → processing → reviewing → finalizing → complete`

---

## Sweep Profiles (`config/sweep_profiles.py`)

| Profile | Vision | OCR | LLM | GPU |
|---------|--------|-----|-----|-----|
| `slow` | yolov8n ONNX, CPU | Claude Haiku API | Claude Haiku | None |
| `standard` | yolov8s, CUDA | PaddleOCR CPU | Ollama 8b | Required |
| `hot` | yolov8m, CUDA | PaddleOCR CUDA | Ollama 70b | Required |
