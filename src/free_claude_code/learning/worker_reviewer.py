"""Reviewer/learning processing over neutral delegated-worker events."""

from .auto_reviewer import AutoReviewResult, PendingReviewerTasks, persist_from_message
from .delegated_worker import DelegatedWorkerEvent, WorkerLifecycle
from .reviewer_flow import build_reviewer_plan
from .reviewer_scars import ReviewerScarError, ScarRegistry


def process_worker_event(
    event: DelegatedWorkerEvent,
    *,
    profile: str | None = None,
) -> AutoReviewResult | None:
    """Process a normalized worker transition without knowing its source schema."""

    try:
        plan = build_reviewer_plan(event.task_input, profile=profile)
    except OSError, ReviewerScarError, ValueError:
        return None

    if event.lifecycle is WorkerLifecycle.BACKGROUND:
        if event.parent_session_id and event.worker_id:
            try:
                PendingReviewerTasks(profile).save(
                    event.parent_session_id,
                    event.worker_id,
                    plan,
                )
            except OSError, ReviewerScarError:
                return None
        return None

    if event.lifecycle is not WorkerLifecycle.COMPLETED:
        return None

    return persist_from_message(
        event.result_text,
        plan=plan,
        registry=ScarRegistry(profile),
    )


def process_background_worker_stop(
    event: DelegatedWorkerEvent,
    *,
    profile: str | None = None,
) -> AutoReviewResult | None:
    """Finish a background worker using its source-independent pending plan."""

    if event.lifecycle is not WorkerLifecycle.COMPLETED:
        return None
    if not event.parent_session_id or not event.worker_id:
        return None
    try:
        plan = PendingReviewerTasks(profile).pop(
            event.parent_session_id,
            event.worker_id,
        )
    except OSError, ReviewerScarError:
        return None
    if plan is None:
        return None
    return persist_from_message(
        event.result_text,
        plan=plan,
        registry=ScarRegistry(profile),
    )


__all__ = ["process_background_worker_stop", "process_worker_event"]
