"""Evaluator-only ground truth; never passed to the planner/executor."""

from mas_recovery.core.schemas import Task
from mas_recovery.environment.simulated import SimulatedWorld


def task_correct(task: Task, world: SimulatedWorld) -> bool:
    total = task.quantity * task.unit_price
    expected = [total] if total <= task.budget else []
    return world.orders == expected
