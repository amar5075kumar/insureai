"""
Agents service entry point.

Architecture:
  - main() subscribes to sweep_created:* and starts handle_new_sweep() per sweep
  - handle_new_sweep() runs graph.astream() + a message_pump() concurrently
  - message_pump() uses BLPOP on Redis list queues and injects events into the
    graph via graph.aupdate_state() — one long-lived connection per sweep
  - idle_node() is a pure sleep (no Redis) — external state injection is safe
    because idle_node returns {} which does not overwrite checkpoint state
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

import redis.asyncio as aioredis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("agents_runner")

_repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if _repo not in sys.path:
    sys.path.insert(0, _repo)

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")


async def message_pump(sweep_id: str, graph, config: dict) -> None:
    """
    Read from Redis list queues and inject events into the graph state.
    One long-lived connection per sweep — no connection churn.
    Exits when the sweep is complete or the task is cancelled.
    """
    queues = [
        f"sweep_end_queue:{sweep_id}",
        f"quality_queue:{sweep_id}",
        f"transcript_queue:{sweep_id}",
    ]
    while True:
        try:
            async with aioredis.from_url(REDIS_URL, decode_responses=True) as r:
                while True:
                    try:
                        result = await r.blpop(queues, timeout=1)
                    except asyncio.CancelledError:
                        return
                    except Exception as e:
                        logger.warning(f"pump blpop error [{sweep_id[:8]}]: {e}")
                        break  # break inner loop → reconnect

                    if result is None:
                        continue

                    key, value = result
                    try:
                        from nodes import deliver_quality, deliver_sweep_end, deliver_transcript
                        if "sweep_end" in key:
                            deliver_sweep_end(sweep_id)
                            logger.info(f"Pump: sweep_end [{sweep_id[:8]}]")
                            # Don't return — graph loops back to idle for post-sweep chat
                        elif "quality" in key:
                            deliver_quality(sweep_id, value)
                        elif "transcript" in key:
                            data = json.loads(value)
                            deliver_transcript(sweep_id, data.get("text", ""), data.get("confidence", 1.0))
                            logger.info(f"Pump: transcript [{sweep_id[:8]}]: {data.get('text','')[:40]!r}")
                    except asyncio.CancelledError:
                        return
                    except Exception as e:
                        logger.warning(f"pump inject error [{sweep_id[:8]}]: {e}")
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"pump connect error [{sweep_id[:8]}]: {e}")
            await asyncio.sleep(2)


async def handle_new_sweep(sweep_id: str, country: str, currency: str) -> None:
    """Launch a LangGraph graph + message pump concurrently for a sweep."""
    from graph import SweepState, build_graph

    db_url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    graph = build_graph(db_url)

    initial_state: SweepState = {
        "sweep_id": sweep_id,
        "country": country,
        "currency": currency,
        "language": "en",
        "sweep_phase": "initializing",
        "conversation_history": [],
        "latest_transcript": None,
        "latest_transcript_confidence": 0.0,
        "pending_agent_response": None,
        "pending_quality_warning": None,
        "book_count_so_far": 0,
        "items_count_so_far": 0,
        "scale_anchor": None,
        "celery_task_ids": [],
        "sweep_end_requested": False,
        "workers_dispatched": False,
        "packet_ready": False,
    }

    config = {"configurable": {"thread_id": sweep_id}}

    pump_task = asyncio.create_task(message_pump(sweep_id, graph, config))

    try:
        async for event in graph.astream(initial_state, config=config):
            node = list(event.keys())[0] if event else "?"
            logger.info(f"Graph step [{sweep_id[:8]}]: {node}")
    except BaseException as e:
        logger.error(f"Graph error for sweep {sweep_id}: {type(e).__name__}: {e}", exc_info=True)
    finally:
        pump_task.cancel()
        try:
            await pump_task
        except asyncio.CancelledError:
            pass


async def main() -> None:
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.psubscribe("sweep_created:*")

    logger.info("Agents runner started — listening for sweep events")

    active_sweeps: dict[str, asyncio.Task] = {}

    async for message in pubsub.listen():
        if message["type"] not in ("message", "pmessage"):
            continue

        channel = message.get("channel", "")
        if not channel.startswith("sweep_created:"):
            continue

        sweep_id = channel.split(":", 1)[1]
        if sweep_id in active_sweeps and not active_sweeps[sweep_id].done():
            continue

        data = json.loads(message["data"])

        # Apply frontend llm_config to env vars for this process so llm_factory picks them up
        llm_config = data.get("llm_config") or {}
        if llm_config.get("provider"):
            os.environ["LLM_PROVIDER"] = llm_config["provider"]
        if llm_config.get("apiKey"):
            os.environ["ANTHROPIC_API_KEY"] = llm_config["apiKey"]
        if llm_config.get("baseUrl"):
            os.environ["BEDROCK_BASE_URL"] = llm_config["baseUrl"]
        if llm_config.get("bearerToken"):
            os.environ["ANTHROPIC_API_KEY"] = llm_config["bearerToken"]
        if llm_config.get("region"):
            os.environ["AWS_REGION"] = llm_config["region"]
        if llm_config:
            logger.info(f"Using frontend LLM config: provider={os.environ.get('LLM_PROVIDER')}")

        task = asyncio.create_task(
            handle_new_sweep(sweep_id, data.get("country", "GB"), data.get("currency", "GBP"))
        )
        active_sweeps[sweep_id] = task
        logger.info(f"Started graph for sweep {sweep_id}")


if __name__ == "__main__":
    asyncio.run(main())
