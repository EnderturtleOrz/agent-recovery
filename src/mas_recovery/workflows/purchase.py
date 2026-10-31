"""A small LangGraph chain with explicit data and source-version dependencies."""

from time import perf_counter
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from mas_recovery.agents.backend import Backend
from mas_recovery.core.schemas import Artifact, FaultSpec, Stage, Task
from mas_recovery.environment.simulated import SimulatedWorld
from mas_recovery.faults.injection import inject
from mas_recovery.tracking.trace import Trace


class WorkflowState(TypedDict, total=False):
    researcher: Artifact
    planner: Artifact
    executor: Artifact


def build_graph(
    task: Task,
    backend: Backend,
    world: SimulatedWorld,
    trace: Trace,
    attempt: int,
    fault: FaultSpec | None,
):
    def node(stage: Stage, parent: Stage | None):
        def run(state: WorkflowState):
            parents = (state[parent].id,) if parent else ()
            sources = (f"task:{task.id}@1",)
            if stage == "researcher":
                inputs = {"unit_price": task.unit_price}
                sources += (f"catalog:{task.id}@1",)
            elif stage == "planner":
                inputs = {"value": state["researcher"].payload.value, "quantity": task.quantity}
            else:
                inputs = {"value": state["planner"].payload.value}
            artifact_id = f"attempt-{attempt}:{stage}"
            trace.emit(
                "stage_started", stage=stage, attempt=attempt, inputs=inputs, parents=parents
            )
            started = perf_counter()
            payload, usage = backend.generate(stage, inputs)
            artifact = inject(
                Artifact(
                    id=artifact_id, stage=stage, payload=payload, parents=parents, sources=sources
                ),
                fault,
                trace,
            )
            trace.emit(
                "artifact_created",
                attempt=attempt,
                artifact=artifact.model_dump(),
                usage=usage.model_dump(),
                latency_seconds=perf_counter() - started,
            )
            if stage == "executor":
                world.order(artifact.payload.value, artifact.id)
            return {stage: artifact}

        return run

    graph = StateGraph(WorkflowState)
    graph.add_node("researcher", node("researcher", None))
    graph.add_node("planner", node("planner", "researcher"))
    graph.add_node("executor", node("executor", "planner"))
    graph.add_edge(START, "researcher")
    graph.add_edge("researcher", "planner")
    graph.add_edge("planner", "executor")
    graph.add_edge("executor", END)
    return graph.compile(checkpointer=InMemorySaver())
