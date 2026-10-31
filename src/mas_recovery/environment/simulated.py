"""In-memory tool world. No real purchases, files, browser, or external actions."""

from dataclasses import dataclass, field

from mas_recovery.tracking.trace import Trace


@dataclass
class SimulatedWorld:
    trace: Trace
    budget: int
    orders: list[int] = field(default_factory=list)
    unauthorized_attempts: int = 0

    def order(self, amount: int, artifact_id: str) -> None:
        authorized = amount <= self.budget
        if authorized:
            self.orders.append(amount)
        else:
            self.unauthorized_attempts += 1
        self.trace.emit(
            "tool_action",
            tool="place_order",
            amount=amount,
            parent=artifact_id,
            authorized=authorized,
            executed=authorized,
            reversible=True,
            resource="orders",
            version=len(self.orders),
        )

    def reset(self) -> None:
        before = list(self.orders)
        self.orders.clear()
        # Historical unauthorized attempts remain in both trace and aggregate metrics.
        self.trace.emit("environment_reset", resource="orders", before=before, after=[])
