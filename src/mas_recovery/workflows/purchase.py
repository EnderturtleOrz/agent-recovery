"""Fixed LangGraph workflow with explicit inputs and versioned provenance."""

from time import perf_counter
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from mas_recovery.agents.backend import Backend
from mas_recovery.core.schemas import Artifact, ExperimentConfig, FaultSpec, Stage, Task
from mas_recovery.environment.simulated import SimulatedWorld
from mas_recovery.evaluation.oracle import verify_payload
from mas_recovery.experiments.meter import Meter
from mas_recovery.faults.injection import InjectedTimeout, inject
from mas_recovery.tracking.trace import Trace


class VerificationFailed(RuntimeError):
    pass


class WorkflowState(TypedDict, total=False):
    researcher: Artifact
    planner: Artifact
    executor: Artifact


def stage_inputs(task: Task, stage: Stage, state: WorkflowState) -> dict:
    if not task.catalog:
        if stage == "researcher":
            return {"unit_price": task.unit_price}
        if stage == "planner":
            return {"value": state["researcher"].payload.value, "quantity": task.quantity}
        return {"value": state["planner"].payload.value}
    if stage == "researcher":
        return {
            "catalog": [
                dict(
                    id=p.id,
                    supplier=p.supplier,
                    unit_price=p.unit_price,
                    stock=p.stock,
                    version=p.version,
                )
                for p in task.catalog
            ]
        }
    if stage == "planner":
        return {
            "research": state["researcher"].payload.model_dump(),
            "quantity": task.quantity,
            "budget": task.budget,
            "allowed_suppliers": list(task.allowed_suppliers),
        }
    return {"plan": state["planner"].payload.model_dump()}


def build_graph(
    task: Task,
    backend: Backend,
    world: SimulatedWorld,
    trace: Trace,
    attempt: int,
    fault: FaultSpec | None,
    config: ExperimentConfig | None = None,
    meter: Meter | None = None,
):
    config = config or ExperimentConfig(name="direct", task_file="unused")
    meter = meter or Meter(config, trace)
    verify = config.recovery == "always_verify"

    def node(stage: Stage, parent: Stage | None):
        def run(state: WorkflowState):
            parents = (state[parent].id,) if parent else ()
            inputs = stage_inputs(task, stage, state)
            sources = (f"task:{task.id}@1",)
            if stage == "researcher":
                sources += (
                    tuple(f"catalog:{p.id}@{p.version}" for p in task.catalog)
                    if task.catalog
                    else (f"catalog:{task.id}@1",)
                )
            for retry in range(1 + (config.verification_retries if verify else 0)):
                artifact_id = f"attempt-{attempt}:{stage}" + (f":retry-{retry}" if retry else "")
                trace.emit(
                    "stage_started",
                    stage=stage,
                    attempt=attempt,
                    retry=retry,
                    artifact_id=artifact_id,
                    inputs=inputs,
                    parents=parents,
                )
                active = fault if retry == 0 else None
                started = perf_counter()
                if active and active.stage == stage and active.kind == "timeout":
                    trace.emit(
                        "fault_injected",
                        artifact_id=artifact_id,
                        fault=active.model_dump(),
                        output_missing=True,
                    )
                    trace.emit(
                        "stage_failed",
                        artifact_id=artifact_id,
                        stage=stage,
                        attempt=attempt,
                        error_type="InjectedTimeout",
                    )
                    if verify and retry < config.verification_retries:
                        trace.emit(
                            "verification",
                            artifact_id=artifact_id,
                            accepted=False,
                            reason="missing_output",
                            verifier="oracle-upper-bound",
                            latency_seconds=0.0,
                        )
                        continue
                    raise InjectedTimeout(stage)
                payload, usage = meter.call(backend, stage, inputs, artifact_id, attempt)
                artifact = inject(
                    Artifact(
                        id=artifact_id,
                        stage=stage,
                        payload=payload,
                        parents=parents,
                        sources=sources,
                    ),
                    active,
                    trace,
                    task,
                )
                trace.emit(
                    "artifact_created",
                    attempt=attempt,
                    artifact=artifact.model_dump(),
                    usage=usage.model_dump(),
                    latency_seconds=perf_counter() - started,
                )
                if verify:
                    check_started = perf_counter()
                    accepted = verify_payload(task, stage, artifact.payload)
                    trace.emit(
                        "verification",
                        artifact_id=artifact_id,
                        accepted=accepted,
                        verifier="oracle-upper-bound",
                        reason="payload_check",
                        latency_seconds=perf_counter() - check_started,
                    )
                    if not accepted:
                        if retry < config.verification_retries:
                            continue
                        raise VerificationFailed(stage)
                if stage == "executor":
                    # A no-purchase decision has no external action. Legacy keeps old behavior.
                    if not task.catalog or artifact.payload.product_id is not None:
                        world.order(artifact.payload.value, artifact.id, artifact.payload)
                return {stage: artifact}
            raise AssertionError("unreachable")

        return run

    graph = StateGraph(WorkflowState)
    for stage, parent in (("researcher", None), ("planner", "researcher"), ("executor", "planner")):
        graph.add_node(stage, node(stage, parent))
    graph.add_edge(START, "researcher")
    graph.add_edge("researcher", "planner")
    graph.add_edge("planner", "executor")
    graph.add_edge("executor", END)
    return graph.compile(checkpointer=InMemorySaver())
