"""
LangGraph state graph for sweep orchestration.

State machine phases:
  initializing → sweeping → processing → reviewing → finalizing → complete

All LLM calls live in nodes. All deterministic work (totals, pricing,
measurement) lives in Celery workers. The graph never writes numbers.
"""
from __future__ import annotations

import operator
from typing import Annotated, List, Literal, Optional, TypedDict

from langgraph.graph import END, StateGraph


# ── Shared state ─────────────────────────────────────────────────────────────

class ConversationMessage(TypedDict):
    role: Literal["user", "agent"]
    content: str
    timestamp_ms: Optional[int]


class SweepState(TypedDict):
    # Session
    sweep_id: str
    country: str
    currency: str
    language: str
    sweep_phase: str  # initializing|sweeping|processing|reviewing|finalizing|complete

    # Conversation
    conversation_history: Annotated[List[ConversationMessage], operator.add]
    latest_transcript: Optional[str]
    latest_transcript_confidence: float
    pending_agent_response: Optional[str]

    # Vision feedback from quality gate
    pending_quality_warning: Optional[str]

    # Live counts (updated by vision pipeline — not stored in state)
    book_count_so_far: int
    items_count_so_far: int

    # Scale calibration (from user voice: "these are 80cm Billy shelves")
    scale_anchor: Optional[dict]

    # Worker task IDs
    celery_task_ids: Annotated[List[str], operator.add]

    # Control flags
    sweep_end_requested: bool
    workers_dispatched: bool
    packet_ready: bool


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_graph(postgres_connection_string: str):
    """
    Build and compile the LangGraph sweep orchestration graph.
    Persists state to PostgreSQL (survives backend restarts).
    """
    from nodes import (
        conversation_agent_node,
        deliver_summary_node,
        dispatch_workers_node,
        handle_quality_warning_node,
        idle_node,
        init_session_node,
        process_transcript_node,
        review_agent_node,
        speak_node,
        wait_workers_node,
    )
    from routing import route_after_speak, route_idle
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    graph = StateGraph(SweepState)

    # ── Nodes ─────────────────────────────────────────────────────────
    graph.add_node("init_session", init_session_node)
    graph.add_node("idle", idle_node)
    graph.add_node("process_transcript", process_transcript_node)
    graph.add_node("handle_quality", handle_quality_warning_node)
    graph.add_node("conversation_agent", conversation_agent_node)
    graph.add_node("speak", speak_node)
    graph.add_node("dispatch_workers", dispatch_workers_node)
    graph.add_node("wait_workers", wait_workers_node)
    graph.add_node("review_agent", review_agent_node)
    graph.add_node("deliver_summary", deliver_summary_node)

    # ── Entry ─────────────────────────────────────────────────────────
    graph.set_entry_point("init_session")
    graph.add_edge("init_session", "idle")

    # ── Main sweep loop ───────────────────────────────────────────────
    graph.add_conditional_edges(
        "idle",
        route_idle,
        {
            "transcript": "process_transcript",
            "quality_warning": "handle_quality",
            "sweep_end": "dispatch_workers",
            "wait": "idle",
        },
    )
    graph.add_edge("process_transcript", "conversation_agent")
    graph.add_edge("handle_quality", "speak")
    graph.add_edge("conversation_agent", "speak")
    graph.add_conditional_edges(
        "speak",
        route_after_speak,
        {
            "continue": "idle",
            "end_sweep": "dispatch_workers",
        },
    )

    # ── Post-sweep pipeline ───────────────────────────────────────────
    graph.add_edge("dispatch_workers", "wait_workers")
    graph.add_edge("wait_workers", "review_agent")
    graph.add_edge("review_agent", "deliver_summary")
    # After packet delivery, loop back to idle so the agent can answer
    # post-sweep questions ("What is the total?", "Which books were identified?")
    graph.add_edge("deliver_summary", "idle")

    # ── Checkpointing ─────────────────────────────────────────────────
    # InMemorySaver is sufficient: sweep state is short-lived per session.
    # Durable data (books, pricing, room geometry) is persisted to PostgreSQL
    # directly by the nodes via asyncpg, independent of graph checkpointing.
    from langgraph.checkpoint.memory import MemorySaver
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)
