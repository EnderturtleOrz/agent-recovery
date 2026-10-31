"""Backend boundary: agent logic consumes explicit inputs, never evaluator truth."""

from typing import Protocol

from mas_recovery.core.schemas import Payload, Stage, Usage


class Backend(Protocol):
    def generate(self, stage: Stage, inputs: dict[str, int]) -> tuple[Payload, Usage]: ...


class FakeBackend:
    """Deterministic contract test double; not evidence of LLM robustness."""

    def generate(self, stage: Stage, inputs: dict[str, int]) -> tuple[Payload, Usage]:
        if stage == "researcher":
            value = inputs["unit_price"]
        elif stage == "planner":
            value = inputs["value"] * inputs["quantity"]
        else:
            value = inputs["value"]
        return Payload(value=value), Usage()
