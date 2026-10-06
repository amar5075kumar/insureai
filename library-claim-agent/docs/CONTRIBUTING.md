# Contributing

## Extension Points

Three stable interfaces. Add a new provider by implementing a function — don't modify the pipeline.

---

### New LLM Provider

**File:** `services/agents/llm_factory.py`

`build_llm()` returns a LangChain `BaseChatModel`. Add a branch:

```python
def build_llm(max_tokens: int = 150, temperature: float = 0.3):
    if LLM_PROVIDER == "my_provider":
        return _build_my_provider(max_tokens, temperature)
    ...

def _build_my_provider(max_tokens, temperature):
    from langchain_my_provider import ChatMyProvider
    return ChatMyProvider(api_key=os.environ["MY_API_KEY"], ...)
```

Then:
1. Add `MY_API_KEY` and `LLM_PROVIDER=my_provider` to `.env.example`
2. The frontend ⚙ Configure AI Provider panel reads from `localStorage` — users can set it there too

---

### New OCR Engine

**File:** `services/worker-lite/book_id_task.py`

`_identify_with_claude()` receives JPEG bytes, returns `{"title": str, "author": str, "language": str}`.

```python
def _identify_with_new_engine(image_bytes: bytes) -> dict:
    # run your model
    return {"title": "...", "author": "...", "language": "en"}
```

For a **GPU engine** (PaddleOCR, EasyOCR with CUDA): don't put it in `worker-lite`.
Add `services/workers/<name>/` + a Dockerfile, have it consume the `book_id` Celery queue.
Stop `worker-lite`, start your worker. The pipeline is unaffected.

---

### New Pricing Source

**File:** `services/worker-lite/pricing_task.py`

`_fetch_google_books_price(isbn, title)` returns `{"amount": float, "source": str}` or `None`.

```python
async def _fetch_my_price_source(isbn: str, title: str) -> dict | None:
    # call your API
    return {"amount": 12.99, "source": "my_source"}
```

For a real scraper (AbeBooks, etc.): add `services/workers/pricing/`, consume `pricing` Celery queue.
Write `replacement_cost_amount` + `replacement_cost_source` to the `books` table — that's the contract.

---

## PR Checklist

- `./scripts/build-local.sh` completes without error
- `docker compose -f docker-compose.local.yml ps` shows all 7 services healthy
- New env vars added to `.env.example` with a comment
- No secrets in compose files or docs
- New containers have a healthcheck in the compose file
