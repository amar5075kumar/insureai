# API Reference

Base URL: `http://localhost:8000`

---

## Health

### `GET /health`
```bash
curl localhost:8000/health
# {"status":"ok","profile":"slow","version":"0.1.0"}
```

---

## Sweeps

### `GET /sweeps` — List all sessions
```bash
curl localhost:8000/sweeps
```
Returns array of sweep summaries with book counts, avg confidence, total value.

### `POST /sweeps` — Create a sweep
```bash
curl -X POST localhost:8000/sweeps \
  -H 'Content-Type: application/json' \
  -d '{"country":"GB","currency":"GBP"}'
# {"sweep_id":"40bc02ba-…","state":"initializing","ws_url":"ws://…"}
```

### `GET /sweeps/{id}` — Current state
```bash
curl localhost:8000/sweeps/40bc02ba-…
```

### `POST /sweeps/{id}/end` — End the sweep
```bash
curl -X POST localhost:8000/sweeps/40bc02ba-…/end
# {"status":"processing"}
```
Triggers: `dispatch_workers → wait_workers → review_agent → deliver_summary → packet`

### `GET /sweeps/{id}/analytics` — Full detail with book table
```bash
curl localhost:8000/sweeps/40bc02ba-…/analytics
```
Returns books with title, author, ISBN, confidence scores, prices, language, crop URL.

### `GET /sweeps/{id}/packet` — Download claim packet ZIP
```bash
curl localhost:8000/sweeps/40bc02ba-…/packet -o claim_packet.zip
```
`404` if packet hasn't been generated yet (call `/end` first).

### `GET /sweeps/{id}/crops/{book_id}` — Spine crop JPEG
```bash
curl localhost:8000/sweeps/40bc02ba-…/crops/06e1e04c-… -o spine.jpg
```

---

## WebSocket `/ws/{sweep_id}`

**Browser → Server:**

```json
{ "type": "user_text", "text": "How many books?" }
{ "type": "sweep_end" }
```

**Server → Browser:**

```json
{ "type": "agent_text", "text": "I've found 14 books so far." }

{ "type": "inventory_update",
  "books": [{"id":"…","status":"identified","title":"A Passage to India",
             "author":"E. M. Forster","replacement_cost":{"amount":11.28,"source":"estimate"},
             "id_confidence":0.8,"detection_confidence":0.63,"crop_url":"/sweeps/…/crops/…"}],
  "items": [] }

{ "type": "processing_progress", "completed": 4, "total": 5 }

{ "type": "sweep_complete", "packet_url": "/sweeps/…/packet" }
```

---

## Webhooks

### `POST /webhooks/frame` — Ingest a camera frame
```bash
curl -X POST localhost:8000/webhooks/frame \
  -F "sweep_id=40bc02ba-…" \
  -F "frame_id=frame_001" \
  -F "timestamp_ms=1000" \
  -F "jpeg_data=@frame.jpg;type=image/jpeg"
# {"queued":true}
```
Used in `direct` camera mode. In `livekit` mode, frames come from LiveKit egress.
