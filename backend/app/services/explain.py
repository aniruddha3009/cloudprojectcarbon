"""Plain-English status labels and one-sentence reasons for the process queue.

Every sentence is derived from the job's stored state and the scheduler's *last recorded decision*
(action, reason text, policy, grid intensity at that moment). Nothing here changes a decision; it only
translates it. The full technical reason is still shown in the "Why this decision?" view.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Callable

STATUS_LABELS = {
    "pending": "Not arrived yet",
    "queued": "Waiting",
    "deferred": "Scheduled for later",
    "running": "Running",
    "paused": "Paused",
    "completed": "Completed",
    "failed": "Failed",
    "cancelled": "Cancelled",
}


def status_label(state: str, now: int | None = None, arrival_slot: int | None = None,
                 planned_slot: int | None = None) -> str:
    if now is not None:
        if state == "pending" and arrival_slot is not None and arrival_slot <= now:
            return "Waiting"  # arrives this step; the scheduler has not looked at it yet
        if state == "deferred" and (planned_slot is None or planned_slot <= now):
            return "Waiting"  # re-checked every step (threshold / reactive policies), not booked for a later time
    return STATUS_LABELS.get(state, state.capitalize())


def last_action(last_decision_key: str | None) -> str | None:
    return last_decision_key.split("|", 1)[0] if last_decision_key else None


def plain_reason(
    *,
    state: str,
    action: str | None,
    reason: str | None,
    policy: str | None,
    intensity: Decimal | None,
    green_threshold: Decimal | None,
    debt_threshold: Decimal | None,
    capacity: Decimal,
    deadline_missed: bool,
    manual_run: bool,
    planned_slot: int | None,
    hold_slot: int | None,
    arrival_slot: int,
    at: Callable[[int | None], str | None],
    now: int | None = None,
) -> str:
    """One short sentence explaining the current state. ``at`` formats a slot as a clock time (or None)."""
    text = reason or ""

    def when(slot: int | None, prefix: str, fallback: str) -> str:
        label = at(slot)
        return f"{prefix} {label}" if label else fallback

    if state == "completed":
        return "Finished, but after its deadline." if deadline_missed else "Finished before its deadline."
    if state == "failed":
        return "Stopped with an error; the energy it used is still counted."
    if state == "cancelled":
        return "Cancelled."
    if state == "pending":
        if now is not None and arrival_slot <= now:
            return "Just arrived; the scheduler decides at the next step."
        return when(arrival_slot, "Arrives at", "Has not arrived yet") + "."
    if state == "paused":
        return "Paused because carbon debt is high; it will resume in time to meet its deadline."

    if state == "running":
        if action == "EMERGENCY_START":
            return "Running now because this is an emergency."
        if action == "START_FORCED":
            if text.startswith("Maximum wait"):
                return "Running now because it has waited as long as it is allowed to."
            return "Running now because its deadline is approaching."
        if action == "REPAYMENT_START":
            return "Running now because electricity is clean; this work repays carbon debt."
        if action == "MANUAL_START":
            return "Running now because it was started manually (it cannot earn a repayment)."
        if action == "THROTTLE":
            return (f"Running at {int(capacity * 100)}% speed because carbon debt is high; "
                    "it will still finish before its deadline.")
        if action == "RESTORE":
            return ("Back to full speed because electricity is clean." if text.startswith("Green slot")
                    else "Back to full speed because carbon debt has come down.")
        if action == "DEADLINE_MISSED":
            return "Still running, but its deadline has already passed."
        if policy == "fifo" or text.startswith("FIFO"):
            return "Running now: this policy ignores carbon and starts work whenever a worker is free."
        if intensity is not None and green_threshold is not None and intensity <= green_threshold:
            return "Running now because electricity is clean."
        if intensity is not None and debt_threshold is not None and intensity <= debt_threshold:
            return "Running now because electricity is below the carbon limit."
        if text.startswith("Runs now: the best feasible window saves under"):
            return "Running now because waiting would save almost no carbon."
        return "Running now because no cleaner time is expected before its deadline."

    # queued / deferred
    if manual_run or action == "OPERATOR_RUN_REQUESTED":
        return "Will start at the next step because it was started manually."
    if action == "OPERATOR_HOLD":
        return when(hold_slot, "Held manually until", "Held manually") + "."
    if action == "DEFER":
        if policy == "debt_predictive" or text.startswith(("Deferred until", "Planned until")):
            return when(planned_slot, "Scheduled for", "Scheduled for later") + " because cleaner electricity is expected."
        if "carbon debt outstanding" in text:
            return "Waiting for clean electricity to repay carbon debt; its deadline still allows it."
        return "Waiting because electricity is carbon-intensive and this process can wait."
    if action == "WAIT_CAPACITY":
        if planned_slot is not None and at(planned_slot):
            return f"Waiting for a free worker; planned to start at {at(planned_slot)}."
        return "Waiting for a free worker."
    return "Just arrived; the scheduler decides at the next step."
