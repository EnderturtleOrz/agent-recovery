"""Per-run call/time admission limits and known-token accounting."""

from time import perf_counter

from mas_recovery.agents.backend import ModelCallError, ModelCallInterrupted
from mas_recovery.core.schemas import ExperimentConfig, Usage
from mas_recovery.tracking.trace import Trace


class BudgetExceeded(RuntimeError):
    def __init__(self, resource: str, *, phase: str = "admission"):
        self.resource = resource
        self.phase = phase
        super().__init__(f"{resource} budget prevents {phase}")


class Meter:
    def __init__(self, config: ExperimentConfig, trace: Trace):
        self.config, self.trace = config, trace
        self.started = perf_counter()
        self.calls = 0
        self.known_tokens = 0
        self.usage_unknown = False

    def check(self, *, before_call: bool = True):
        phase = "admission" if before_call else "completion"
        if perf_counter() - self.started >= self.config.max_seconds:
            raise BudgetExceeded("time", phase=phase)
        limit = self.config.max_total_tokens
        if limit is not None:
            if self.usage_unknown:
                raise BudgetExceeded("unknown_tokens", phase=phase)
            # Consuming exactly the allowance is valid; only another call is forbidden.
            exhausted = self.known_tokens >= limit if before_call else self.known_tokens > limit
            if exhausted:
                raise BudgetExceeded("tokens", phase=phase)

    def call(self, backend, stage, inputs, artifact_id, attempt):
        self.check()
        if self.calls >= self.config.max_calls:
            raise BudgetExceeded("calls")
        self.calls += 1
        if hasattr(backend, "max_output_tokens"):
            backend.max_output_tokens = self.config.max_output_tokens
            backend.timeout_seconds = max(
                0.001, min(60.0, self.config.max_seconds - (perf_counter() - self.started))
            )
        self.trace.emit("call_started", stage=stage, artifact_id=artifact_id, attempt=attempt)
        started = perf_counter()
        usage = Usage(model_calls=0, input_tokens=None, output_tokens=None)
        status, error_type = "completed", None
        try:
            payload, usage = backend.generate(stage, inputs)
        except KeyboardInterrupt as error:
            status, error_type = "interrupted", "KeyboardInterrupt"
            if isinstance(error, ModelCallInterrupted):
                usage = error.usage
            raise
        except Exception as error:
            status = "failed"
            error_type = (
                error.error_type if isinstance(error, ModelCallError) else type(error).__name__
            )
            if isinstance(error, ModelCallError):
                usage = error.usage
            raise
        finally:
            self.known_tokens += (usage.input_tokens or 0) + (usage.output_tokens or 0)
            self.usage_unknown |= usage.input_tokens is None or usage.output_tokens is None
            self.trace.emit(
                "call_finished",
                stage=stage,
                artifact_id=artifact_id,
                attempt=attempt,
                status=status,
                error_type=error_type,
                usage=usage.model_dump(),
                latency_seconds=perf_counter() - started,
                model_record=getattr(backend, "last_record", None),
            )
        self.check(before_call=False)
        return payload, usage
