from enum import StrEnum


class TaskStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ALLOWED_TRANSITIONS = {
    TaskStatus.CREATED: {
        TaskStatus.QUEUED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.QUEUED: {
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
    },
    TaskStatus.RUNNING: {
        TaskStatus.WAITING_FOR_INPUT,
        TaskStatus.WAITING_FOR_APPROVAL,
        TaskStatus.VERIFYING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_FOR_INPUT: {
        TaskStatus.QUEUED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.WAITING_FOR_APPROVAL: {
        TaskStatus.QUEUED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.VERIFYING: {
        TaskStatus.COMPLETED,
        TaskStatus.RUNNING,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


def validate_transition(current: TaskStatus, new: TaskStatus):
    if new not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(
            f"Cannot change task status from '{current}' to '{new}'"
        )