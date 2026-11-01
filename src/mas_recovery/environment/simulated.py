"""Local order ledger with authorization enforcement and explicit reset semantics."""

from dataclasses import dataclass, field

from mas_recovery.core.schemas import Payload, Task
from mas_recovery.tracking.trace import Trace


@dataclass
class SimulatedWorld:
    trace: Trace
    budget: int
    task: Task | None = None
    orders: list[int] = field(default_factory=list)
    order_details: list[dict] = field(default_factory=list)
    unauthorized_attempts: int = 0
    action_version: int = 0

    def order(self, amount: int, artifact_id: str, payload: Payload | None = None) -> None:
        reasons = []
        if sum(self.orders) + amount > self.budget:
            reasons.append("budget")
        if self.task and self.task.catalog:
            if payload is None or payload.supplier not in self.task.allowed_suppliers:
                reasons.append("supplier")
        authorized = not reasons
        detail = payload.model_dump() if payload else {"value": amount}
        if authorized:
            self.orders.append(amount)
            self.order_details.append(detail)
        else:
            self.unauthorized_attempts += 1
        self.action_version += 1
        self.trace.emit(
            "tool_action",
            tool="place_order",
            amount=amount,
            parent=artifact_id,
            authorized=authorized,
            executed=authorized,
            rejection_reasons=reasons,
            payload=detail,
            reversible=True,
            resource="orders",
            version=self.action_version,
        )

    def reset(self) -> None:
        before = list(self.orders)
        self.orders.clear()
        self.order_details.clear()
        self.action_version += 1
        self.trace.emit(
            "environment_reset",
            resource="orders",
            before=before,
            after=[],
            version=self.action_version,
        )
