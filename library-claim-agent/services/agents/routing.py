"""
LangGraph routing functions.
These are pure functions — no I/O, no side effects.
"""
from __future__ import annotations

from graph import SweepState


def route_idle(state: SweepState) -> str:
    """
    Decide what to do from the idle state.
    Priority: sweep_end > quality_warning > user transcript > wait
    After packet is ready, keep looping to answer post-sweep questions.
    """
    # Only route to sweep_end if we haven't already dispatched workers
    if state.get("sweep_end_requested") and not state.get("workers_dispatched"):
        return "sweep_end"
    if state.get("pending_quality_warning"):
        return "quality_warning"
    if state.get("latest_transcript"):
        return "transcript"
    return "wait"


def route_after_speak(state: SweepState) -> str:
    """After the agent speaks, decide whether to end the sweep or continue."""
    # Only dispatch workers once; after packet_ready just keep chatting
    if state.get("sweep_end_requested") and state.get("workers_dispatched") and not state.get("packet_ready"):
        return "end_sweep"
    return "continue"
