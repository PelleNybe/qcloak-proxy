"""Abstract base classes and types for quantum execution backend adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum

from pydantic import BaseModel
from qiskit import QuantumCircuit


class BackendJobStatus(StrEnum):
    """Normalized execution status across local and cloud quantum backends."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BackendInfo(BaseModel):
    """Metadata describing a registered quantum backend."""

    name: str
    backend_type: str
    num_qubits: int
    is_simulator: bool
    has_noise_model: bool = False


class QuantumBackendAdapter(ABC):
    """Abstract async adapter for submitting cloaked circuits to a quantum backend."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique backend identifier."""

    @property
    @abstractmethod
    def info(self) -> BackendInfo:
        """Return metadata about this backend."""

    @abstractmethod
    async def submit(self, circuit: QuantumCircuit, shots: int = 1024) -> str:
        """Submit a single cloaked circuit and return the backend job ID."""

    @abstractmethod
    async def status(self, backend_job_id: str) -> BackendJobStatus:
        """Query execution status for ``backend_job_id``."""

    @abstractmethod
    async def result(self, backend_job_id: str) -> dict[str, int]:
        """Retrieve raw bitstring counts for a completed ``backend_job_id``."""

    async def cancel(self, backend_job_id: str) -> bool:
        """Attempt to cancel a running job. Returns True if cancelled."""
        return False

    async def close(self) -> None:
        """Release any underlying network or compute resources."""
        return None
