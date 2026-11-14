"""Interpret program receipts and finalize an episode without owning task state."""


def _taken_over(result: dict) -> dict | None:
    """The worker's reason when a step was refused because the user brought a window of
    theirs to the front (a worker that sends the user's real input), else None."""
    for item in result.get("events") or []:
        for reason in ((item.get("event") or {}).get("detail") or {}).get("reasons") or []:
            if isinstance(reason, dict) and reason.get("took_over"):
                return reason
    return None


def _cell_usage(summary: dict, result: dict) -> None:
    """Fold what a program did below the high level into the episode summary: events
    its handlers resolved, the one that escalated, and model calls made from inside
    the program (pointing and questions)."""
    summary["events_handled"] += sum(1 for item in result.get("events", []) if item.get("handled"))
    summary["events_escalated"] += 1 if result.get("status") == "escalated" else 0
    from harness.runtime.decision.model import add_usage

    for role, usage in (result.get("usage") or {}).items():
        add_usage(summary, usage)
        if role == "verifier":
            summary["verifier_calls"] += int(usage.get("calls") or 0)
        else:
            summary["vision_calls"] += int(usage.get("calls") or 0)
            summary["vision_cost_usd"] += float(usage.get("cost_usd") or 0.0)


def _wrap_up(kernel, trace):
    """The benchmark's end-of-episode convention, the same for every layer: the kernel
    returns the body to its start pose when the embodiment profile asks for it."""
    try:
        # (A paused run that ends is wrapped up all the same.)
        kernel.resume()
        result = kernel.run("__wrap_up__()", timeout=120)
        trace.emit("wrap_up", status=result["status"], error=result.get("error"),
                   events=[event.get("event", {}).get("kind") for event in result.get("events") or []])
    except Exception as error:
        trace.emit("cleanup_error", message=f"wrap_up: {type(error).__name__}: {error}")
