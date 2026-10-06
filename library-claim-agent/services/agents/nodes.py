"""
LangGraph node implementations.

Each node is an async function: SweepState → SweepState.
Nodes that call LLMs: conversation_agent_node, review_agent_node.
All other nodes are deterministic.

The conversation agent has a hard rule: it NEVER writes prices.
The system prompt enforces this and tests verify it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from graph import SweepState

logger = logging.getLogger(__name__)

# ── System prompt (enforces no-price-writing rule) ────────────────────────────

_SYSTEM_PROMPT = """\
You are a professional insurance claim agent helping a policyholder document \
their home library via a live video sweep.

PERSONALITY: calm, professional, efficient. Short sentences. No filler.

GOALS DURING SWEEP:
1. Confirm country + currency at session start (if not already confirmed)
2. Guide systematic scan: left to right, shelf by shelf
3. Comment briefly on what you're logging
4. Give quality directions (slow down, closer) when vision signals issues
5. Ask clarifying questions for art/items you can't classify

HARD RULES — NEVER BREAK:
- NEVER state a price. You have no access to prices during the sweep.
- NEVER identify a book title unless inventory confirms it with confidence ≥70%.
- Art, portraits, signed books → always say "I've flagged that for human appraisal"
- During sweep: keep ALL responses under 25 words (user is moving)
- After sweep: you may be more detailed

CURRENT INVENTORY:
{inventory_summary}

Country: {country} | Currency: {currency} | Phase: {sweep_phase}
"""


def _build_llm(profile_name: str, tokens: int):
    """Build LLM using the factory — supports Bedrock/Enterprise Gateway, Anthropic, OpenAI."""
    from llm_factory import build_llm
    return build_llm(max_tokens=tokens)


# ── Node implementations ──────────────────────────────────────────────────────

async def init_session_node(state: SweepState) -> SweepState:
    """
    Session initialisation: set initial sweep state in DB.
    The agent will greet the user on the first idle→transcript cycle.
    """
    import asyncpg
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(
            "UPDATE sweeps SET state = 'sweeping' WHERE id = $1",
            state["sweep_id"],
        )
    finally:
        await conn.close()

    logger.info(f"Sweep {state['sweep_id']} initialised")
    return {**state, "sweep_phase": "sweeping"}


# In-process per-sweep message queues — written by message_pump, read by idle_node.
# Single-threaded asyncio: no locks needed.
_pending_transcripts: dict[str, tuple[str, float]] = {}   # sweep_id → (text, confidence)
_pending_sweep_ends: set[str] = set()
_pending_quality: dict[str, str] = {}
_idle_loop_count: dict[str, int] = {}   # sweep_id → idle iteration counter


def deliver_transcript(sweep_id: str, text: str, confidence: float = 1.0) -> None:
    _pending_transcripts[sweep_id] = (text, confidence)


def deliver_sweep_end(sweep_id: str) -> None:
    _pending_sweep_ends.add(sweep_id)


def deliver_quality(sweep_id: str, warning: str) -> None:
    _pending_quality[sweep_id] = warning


async def idle_node(state: SweepState) -> SweepState:
    """
    Check in-process message queues written by the pump, then sleep briefly.
    Returns only changed keys — never spreads **state, which would trigger
    operator.add reducers on conversation_history/celery_task_ids and grow them.
    """
    sweep_id = state["sweep_id"]

    if sweep_id in _pending_sweep_ends:
        _pending_sweep_ends.discard(sweep_id)
        return {"sweep_end_requested": True}  # type: ignore[return-value]

    if sweep_id in _pending_quality:
        warning = _pending_quality.pop(sweep_id)
        return {"pending_quality_warning": warning}  # type: ignore[return-value]

    if sweep_id in _pending_transcripts:
        text, conf = _pending_transcripts.pop(sweep_id)
        return {  # type: ignore[return-value]
            "latest_transcript": text,
            "latest_transcript_confidence": conf,
        }

    # Every 20 idle loops (~3s), refresh book/item counts from DB so the agent
    # knows how many books have been detected by vision.
    count = _idle_loop_count.get(sweep_id, 0) + 1
    _idle_loop_count[sweep_id] = count
    if count % 20 == 0:
        try:
            import asyncpg
            url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
            conn = await asyncpg.connect(url)
            try:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS books FROM books WHERE sweep_id=$1", sweep_id
                )
                irow = await conn.fetchrow(
                    "SELECT COUNT(*) AS items FROM items WHERE sweep_id=$1", sweep_id
                )
                new_books = int(row["books"])
                new_items = int(irow["items"])
            finally:
                await conn.close()
            changes: dict = {}
            if new_books != state.get("book_count_so_far", 0):
                changes["book_count_so_far"] = new_books
            if new_items != state.get("items_count_so_far", 0):
                changes["items_count_so_far"] = new_items
            if changes:
                return changes  # type: ignore[return-value]
        except Exception as e:
            logger.debug(f"Book count refresh failed [{sweep_id[:8]}]: {e}")

    await asyncio.sleep(0.15)
    return {}  # type: ignore[return-value]


async def process_transcript_node(state: SweepState) -> SweepState:
    """
    Process incoming user transcript: store in conversation history, clear flag.
    """
    transcript = state.get("latest_transcript", "")
    if transcript:
        new_msg = {
            "role": "user",
            "content": transcript,
            "timestamp_ms": None,
        }
        return {
            **state,
            "conversation_history": [new_msg],
            "latest_transcript": None,
        }
    return state


async def handle_quality_warning_node(state: SweepState) -> SweepState:
    """Convert quality warning to pending agent response."""
    warning = state.get("pending_quality_warning", "")
    return {
        **state,
        "pending_agent_response": warning,
        "pending_quality_warning": None,
    }


async def conversation_agent_node(state: SweepState) -> SweepState:
    """
    Main conversation node — calls LLM with current context.
    The LLM may call tools to update inventory or set scale anchors.
    """
    from tools import make_sweep_tools
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    profile_name = os.environ.get("SWEEP_PROFILE", "standard")
    max_tokens = 80 if state["sweep_phase"] == "sweeping" else 200
    llm = _build_llm(profile_name, max_tokens)

    # Build inventory summary (brief, for prompt injection)
    inventory_summary = (
        f"{state['book_count_so_far']} books detected, "
        f"{state['items_count_so_far']} items"
    )

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT.format(
            inventory_summary=inventory_summary,
            country=state["country"],
            currency=state["currency"],
            sweep_phase=state["sweep_phase"],
        ))
    ]

    # Last 8 conversation turns
    for msg in state.get("conversation_history", [])[-8:]:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))

    tools = make_sweep_tools(state["sweep_id"])
    llm_with_tools = llm.bind_tools(tools)

    try:
        response = await llm_with_tools.ainvoke(messages)
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        response_text = "Sorry, I had a brief issue. Please continue scanning."
        return {**state, "pending_agent_response": response_text}

    # Execute tool calls
    sweep_ended = False
    if hasattr(response, "tool_calls") and response.tool_calls:
        for tc in response.tool_calls:
            try:
                tool_fn = next((t for t in tools if t.name == tc["name"]), None)
                if tool_fn:
                    result = await tool_fn.ainvoke(tc["args"])
                    if result == "SWEEP_END_SIGNAL":
                        sweep_ended = True
            except Exception as e:
                logger.error(f"Tool {tc['name']} failed: {e}")

    response_text = response.content or ""

    # Store agent message in history
    agent_msg = {"role": "agent", "content": response_text, "timestamp_ms": None}

    return {
        **state,
        "conversation_history": [agent_msg],
        "pending_agent_response": response_text,
        "sweep_end_requested": state.get("sweep_end_requested", False) or sweep_ended,
    }


async def speak_node(state: SweepState) -> SweepState:
    """
    Synthesise pending agent response to audio and push to WebSocket.
    """
    text = state.get("pending_agent_response", "")
    logger.info(f"speak_node: text={repr(text[:80]) if text else 'EMPTY'}")
    if not text.strip():
        return state

    try:
        import redis.asyncio as aioredis

        r = await aioredis.from_url(
            os.environ.get("REDIS_URL", "redis://redis:6379/0"),
            decode_responses=True,
        )
        n = await r.publish(
            f"agent_response:{state['sweep_id']}",
            json.dumps({"text": text}),
        )
        await r.aclose()
        logger.info(f"speak_node: published to {n} subscriber(s)")
    except Exception as e:
        logger.warning(f"Failed to publish agent response: {e}", exc_info=True)

    return {**state, "pending_agent_response": None}


async def dispatch_workers_node(state: SweepState) -> SweepState:
    """
    Dispatch all background Celery workers after sweep ends.
    Also fetches the 1fps frame IDs for the measurement worker.
    """
    import asyncpg
    from celery import Celery as _Celery

    _redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    _celery = _Celery(broker=_redis_url, backend=_redis_url.replace("/0", "/1"))

    sweep_id = state["sweep_id"]
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    conn = await asyncpg.connect(url)

    try:
        # Update sweep state
        await conn.execute(
            "UPDATE sweeps SET state = 'processing' WHERE id = $1", sweep_id
        )

        # Get all unprocessed books (no ISBN yet — need OCR)
        unprocessed = await conn.fetch(
            "SELECT id, frame_ref FROM books WHERE sweep_id = $1 AND status = 'processing'",
            sweep_id,
        )

        # Get all 1fps frames for measurement
        all_frames = await conn.fetch(
            "SELECT id FROM frames WHERE sweep_id = $1 ORDER BY timestamp_ms",
            sweep_id,
        )
        frame_ids = [str(r["id"]) for r in all_frames]
    finally:
        await conn.close()

    task_ids = []

    # Dispatch book ID tasks
    for row in unprocessed:
        t = _celery.send_task(
            "workers.book_id.identify_book",
            kwargs={
                "sweep_id": sweep_id,
                "book_id": str(row["id"]),
                "frame_id": str(row["id"]),
                "crop_s3_key": f"{sweep_id}/crops/{row['id']}.jpg",
            },
            queue="book_id",
        )
        task_ids.append(t.id)

    # Dispatch measurement task
    scale_anchor = state.get("scale_anchor")
    t = _celery.send_task(
        "workers.measurement.measure_room",
        kwargs={
            "sweep_id": sweep_id,
            "frame_ids": frame_ids[::5],
            "scale_anchor": scale_anchor,
        },
        queue="measurement",
    )
    task_ids.append(t.id)

    logger.info(
        f"Dispatched {len(unprocessed)} book ID tasks + 1 measurement task "
        f"for sweep {sweep_id}"
    )

    return {**state, "celery_task_ids": task_ids, "workers_dispatched": True}


async def wait_workers_node(state: SweepState) -> SweepState:
    """
    Wait for book identification + pricing workers to finish.
    Uses DB book status as ground truth (not Celery AsyncResult which requires
    a properly configured backend). Times out at 45 seconds for local stack.
    """
    import asyncpg
    import redis.asyncio as aioredis

    sweep_id = state["sweep_id"]
    deadline = asyncio.get_event_loop().time() + 45  # 45s budget (was 4min)
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    r = await aioredis.from_url(redis_url)
    try:
        while asyncio.get_event_loop().time() < deadline:
            # Use DB book status as real completion signal
            conn = await asyncpg.connect(url)
            try:
                row = await conn.fetchrow(
                    """SELECT COUNT(*) AS total,
                              COUNT(*) FILTER (WHERE status != 'processing') AS done
                       FROM books WHERE sweep_id = $1""",
                    sweep_id,
                )
            finally:
                await conn.close()

            total = int(row["total"] or 0)
            done = int(row["done"] or 0)
            # Count currently processing as pending
            pending = total - done

            await r.publish(
                f"ws_broadcast:{sweep_id}",
                json.dumps({
                    "type": "processing_progress",
                    "completed": done,
                    "total": max(total, 1),
                }),
            )

            if pending == 0:
                break

            await asyncio.sleep(3)
    finally:
        await r.aclose()

    return state


async def review_agent_node(state: SweepState) -> SweepState:
    """
    Post-sweep review: run deterministic checks + LLM audit.
    Populates review_queue.
    """
    import asyncpg
    from review import run_review

    sweep_id = state["sweep_id"]
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    conn = await asyncpg.connect(url)
    try:
        count = await run_review(sweep_id, conn)
        await conn.execute(
            "UPDATE sweeps SET state = 'reviewing' WHERE id = $1", sweep_id
        )
    finally:
        await conn.close()

    logger.info(f"Review complete for {sweep_id}: {count} review items")
    return state


async def deliver_summary_node(state: SweepState) -> SweepState:
    """
    Build the claim packet, generate the report, push complete event.
    """
    import asyncpg
    from output.packet_builder import build_and_save_packet

    sweep_id = state["sweep_id"]

    try:
        # 15s timeout prevents MinIO/network hangs from blocking the graph
        await asyncio.wait_for(build_and_save_packet(sweep_id), timeout=15.0)
    except asyncio.TimeoutError:
        logger.warning(f"Packet generation timed out for {sweep_id} — continuing without packet")
    except Exception as e:
        logger.error(f"Packet generation failed for {sweep_id}: {e}")

    # Notify browser
    import redis.asyncio as aioredis
    r = await aioredis.from_url(
        os.environ.get("REDIS_URL", "redis://redis:6379/0")
    )
    try:
        await r.publish(
            f"ws_broadcast:{sweep_id}",
            json.dumps({
                "type": "sweep_complete",
                "packet_url": f"/sweeps/{sweep_id}/packet",
            }),
        )
    finally:
        await r.aclose()

    return {**state, "packet_ready": True, "sweep_phase": "complete"}
