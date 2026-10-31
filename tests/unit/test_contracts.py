import pytest
from pydantic import ValidationError

from mas_recovery.core.schemas import Artifact, ExperimentConfig, FaultSpec, Payload
from mas_recovery.recovery.policy import FullRestart


def test_unsupported_faults_and_typos_are_rejected():
    with pytest.raises(ValidationError):
        FaultSpec(kind="stale")
    with pytest.raises(ValidationError):
        ExperimentConfig(name="test", task_file="test.json", backend="fkae")
    with pytest.raises(ValidationError):
        ExperimentConfig(name="test", task_file="test.json", unknown_option=True)


def test_restart_rejects_unknown_fault_identity():
    artifact = Artifact(id="known", stage="researcher", payload=Payload(value=10))
    with pytest.raises(ValueError, match="Faulty artifact"):
        FullRestart().plan("other-run", (artifact,))
