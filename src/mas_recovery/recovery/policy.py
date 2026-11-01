"""Recovery planning contract. Detection is supplied separately by the experiment."""

from dataclasses import dataclass
from typing import Protocol

from mas_recovery.core.schemas import Artifact, Stage


@dataclass(frozen=True)
class RecoveryPlan:
    rerun_stages: tuple[Stage, ...]
    retained_artifact_ids: tuple[str, ...]
    reset_environment: bool


class RecoveryPolicy(Protocol):
    def plan(
        self, faulty_id: str, artifacts: tuple[Artifact, ...], failed_stage: Stage | None = None
    ) -> RecoveryPlan: ...


class FullRestart:
    def plan(
        self, faulty_id: str, artifacts: tuple[Artifact, ...], failed_stage: Stage | None = None
    ) -> RecoveryPlan:
        if faulty_id not in {artifact.id for artifact in artifacts} and not (
            failed_stage is not None and faulty_id == f"attempt-0:{failed_stage}"
        ):
            raise ValueError("Faulty artifact must belong to the supplied attempt.")
        return RecoveryPlan(("researcher", "planner", "executor"), (), True)
