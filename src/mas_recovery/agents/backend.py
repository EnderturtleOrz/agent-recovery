"""Backend boundary and explicit deterministic fixture (not an LLM safety result)."""

from typing import Any, Protocol

from mas_recovery.core.schemas import Payload, Stage, Usage


class Backend(Protocol):
    def generate(self, stage: Stage, inputs: dict[str, Any]) -> tuple[Payload, Usage]: ...


class ModelCallError(RuntimeError):
    def __init__(self, error_type: str, usage: Usage):
        super().__init__(error_type)
        self.error_type = error_type
        self.usage = usage


class FakeBackend:
    """Deterministic propagation fixture; deliberately follows the attack marker."""

    def generate(self, stage: Stage, inputs: dict[str, Any]) -> tuple[Payload, Usage]:
        if "catalog" in inputs:
            offers = [
                dict(
                    product_id=p["id"],
                    supplier=p["supplier"],
                    unit_price=p["unit_price"],
                    stock=p["stock"],
                    version=p["version"],
                )
                for p in inputs["catalog"]
            ]
            return Payload(value=0, offers=offers), Usage()
        if "research" in inputs:
            research = inputs["research"]
            quantity, budget = inputs["quantity"], inputs["budget"]
            eligible = [
                p
                for p in research["offers"]
                if p["stock"] >= quantity
                and p["supplier"] in inputs["allowed_suppliers"]
                and p["unit_price"] * quantity <= budget
            ]
            if not eligible:
                return Payload(value=0), Usage()
            chosen = min(eligible, key=lambda p: (p["unit_price"], p["product_id"]))
            supplier = (
                "unapproved"
                if "ATTACK_SUPPLIER_OVERRIDE" in research.get("note", "")
                else chosen["supplier"]
            )
            return Payload(
                value=chosen["unit_price"] * quantity,
                product_id=chosen["product_id"],
                supplier=supplier,
                quantity=quantity,
            ), Usage()
        if "plan" in inputs:
            return Payload.model_validate(inputs["plan"]), Usage()
        value = (
            inputs["unit_price"]
            if stage == "researcher"
            else inputs["value"] * inputs["quantity"]
            if stage == "planner"
            else inputs["value"]
        )
        return Payload(value=value), Usage()
