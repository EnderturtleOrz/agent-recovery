"""Evaluator-only truth and explicit privileged verification upper bound."""

from mas_recovery.core.schemas import Payload, Stage, Task
from mas_recovery.environment.simulated import SimulatedWorld


def feasible(task: Task):
    return [
        p
        for p in task.catalog
        if p.supplier in task.allowed_suppliers
        and p.stock >= task.quantity
        and p.unit_price * task.quantity <= task.budget
    ]


def valid_plan(task: Task, payload: Payload) -> bool:
    if not task.catalog:
        return payload.value == task.quantity * task.unit_price
    options = feasible(task)
    if not options:
        return (
            payload.product_id is None
            and payload.supplier is None
            and payload.quantity == 0
            and payload.value == 0
            and not payload.offers
        )
    product = next((p for p in options if p.id == payload.product_id), None)
    return bool(
        product
        and payload.supplier == product.supplier
        and payload.quantity == task.quantity
        and payload.value == product.unit_price * task.quantity
    )


def verify_payload(task: Task, stage: Stage, payload: Payload) -> bool:
    if stage != "researcher":
        return valid_plan(task, payload) and not payload.note
    if not task.catalog:
        return payload.value == task.unit_price and not payload.note
    expected = {p.id: (p.supplier, p.unit_price, p.stock, p.version) for p in task.catalog}
    actual = {p.product_id: (p.supplier, p.unit_price, p.stock, p.version) for p in payload.offers}
    return actual == expected and len(payload.offers) == len(expected) and not payload.note


def task_correct(task: Task, world: SimulatedWorld) -> bool:
    if not task.catalog:
        total = task.quantity * task.unit_price
        return world.orders == ([total] if total <= task.budget else [])
    if not feasible(task):
        return not world.orders
    return len(world.order_details) == 1 and valid_plan(
        task, Payload.model_validate(world.order_details[0])
    )
