"""Injection metadata stays outside agent-visible artifacts."""

from mas_recovery.core.schemas import Artifact, FaultSpec, Payload
from mas_recovery.tracking.trace import Trace


def inject(artifact: Artifact, fault: FaultSpec | None, trace: Trace) -> Artifact:
    if fault is None or artifact.stage != fault.stage:
        return artifact
    changed = artifact.model_copy(
        update={"payload": Payload(value=artifact.payload.value + fault.delta)}
    )
    trace.emit(
        "fault_injected",
        artifact_id=artifact.id,
        fault=fault.model_dump(),
        before=artifact.payload.model_dump(),
        after=changed.payload.model_dump(),
    )
    return changed
