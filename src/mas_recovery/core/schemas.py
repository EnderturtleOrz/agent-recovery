"""Shared contracts. Changes here require coordination between module owners."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Stage = Literal["researcher", "planner", "executor"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Task(Record):
    id: str
    quantity: int = Field(gt=0, strict=True)
    unit_price: int = Field(gt=0, strict=True)
    budget: int = Field(gt=0, strict=True)


class Payload(Record):
    """Unit price for researcher; total cost for planner and executor (integer cents)."""

    value: int = Field(ge=0, strict=True)


class Usage(Record):
    model_calls: int = 0
    input_tokens: int | None = 0
    output_tokens: int | None = 0


class Artifact(Record):
    id: str
    stage: Stage
    payload: Payload
    parents: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


class FaultSpec(Record):
    # Only the implemented fault is accepted. Unsupported types must not silently no-op.
    kind: Literal["incorrect_result"]
    category: Literal["accidental"] = "accidental"
    stage: Literal["researcher", "planner"] = "researcher"
    delta: int = Field(default=7, gt=0)


class ExperimentConfig(Record):
    name: str
    backend: Literal["fake", "tritonai"] = "fake"
    task_file: str
    recovery: Literal["none", "full_restart"] = "none"
    fault: FaultSpec | None = None
