"""Validated, versioned experiment contracts; money is integer cents."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Stage = Literal["researcher", "planner", "executor"]
STAGES: tuple[Stage, ...] = ("researcher", "planner", "executor")


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Product(Record):
    id: str
    supplier: str
    unit_price: int = Field(gt=0, strict=True)
    stock: int = Field(ge=0, strict=True)
    version: int = Field(ge=1, strict=True)
    previous_price: int = Field(gt=0, strict=True)
    previous_stock: int = Field(ge=0, strict=True)
    previous_version: int = Field(ge=1, strict=True)

    @model_validator(mode="after")
    def versions(self):
        if self.previous_version >= self.version:
            raise ValueError("Previous catalog version must precede current version")
        return self


class Task(Record):
    id: str
    quantity: int = Field(gt=0, strict=True)
    unit_price: int = Field(gt=0, strict=True)
    budget: int = Field(gt=0, strict=True)
    catalog: tuple[Product, ...] = ()
    allowed_suppliers: tuple[str, ...] = ("approved",)

    @model_validator(mode="after")
    def unique_products(self):
        if len({p.id for p in self.catalog}) != len(self.catalog):
            raise ValueError("Product IDs must be unique")
        if not self.allowed_suppliers:
            raise ValueError("At least one authorized supplier is required")
        return self


class Offer(Record):
    product_id: str
    supplier: str
    unit_price: int = Field(gt=0, strict=True)
    stock: int = Field(ge=0, strict=True)
    version: int = Field(ge=1, strict=True)


class Payload(Record):
    value: int = Field(ge=0, strict=True)
    offers: tuple[Offer, ...] = ()
    product_id: str | None = None
    supplier: str | None = None
    quantity: int = Field(default=0, ge=0, strict=True)
    note: str = ""


class PlanResponse(Record):
    """Model-facing decision only; research belongs to the research artifact."""

    value: int = Field(ge=0, strict=True)
    product_id: str | None
    supplier: str | None
    quantity: int = Field(ge=0, strict=True)


def plan_fields(payload: Payload) -> dict:
    """Project decision fields without correcting any amount, identity or quantity."""
    return payload.model_dump(include=set(PlanResponse.model_fields))


class Usage(Record):
    model_calls: int = Field(default=0, ge=0, strict=True)
    input_tokens: int | None = Field(default=0, ge=0, strict=True)
    output_tokens: int | None = Field(default=0, ge=0, strict=True)


class Artifact(Record):
    id: str
    stage: Stage
    payload: Payload
    parents: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


class FaultSpec(Record):
    kind: Literal["incorrect_result", "stale_output", "timeout", "malicious_instruction"]
    category: Literal["accidental", "adversarial"] | None = None
    stage: Literal["researcher", "planner"] = "researcher"
    delta: int = Field(default=7, gt=0, strict=True)

    @model_validator(mode="after")
    def classify(self):
        expected = "adversarial" if self.kind == "malicious_instruction" else "accidental"
        if self.category is not None and self.category != expected:
            raise ValueError("Fault category does not match kind")
        object.__setattr__(self, "category", expected)
        if self.kind in ("stale_output", "malicious_instruction") and self.stage != "researcher":
            raise ValueError("Stale and instruction cases currently target researcher output only")
        return self


class ExperimentConfig(Record):
    name: str
    backend: Literal["fake", "tritonai"] = "fake"
    task_file: str
    recovery: Literal["none", "full_restart", "always_verify"] = "none"
    fault: FaultSpec | None = None
    max_calls: int = Field(default=12, ge=1, strict=True)
    max_seconds: float = Field(default=120, gt=0, strict=True, allow_inf_nan=False)
    max_total_tokens: int | None = Field(default=None, ge=1, strict=True)
    max_output_tokens: int = Field(default=2048, ge=1, strict=True)
    verification_retries: int = Field(default=1, ge=0, le=3, strict=True)
    tracking: bool = True
    replicate: int = Field(default=0, ge=0, strict=True)
