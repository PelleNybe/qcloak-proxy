"""Local Qiskit Aer simulator backend adapter (noiseless and realistic noise models)."""

from __future__ import annotations

import asyncio
import uuid

from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error

from qcloak_proxy.backends.base import BackendInfo, BackendJobStatus, QuantumBackendAdapter


def build_realistic_noise_model(
    depolarizing_1q: float = 0.001,
    depolarizing_2q: float = 0.01,
    readout_error: float = 0.015,
) -> NoiseModel:
    """Construct a realistic superconducting-like Aer noise model.

    Includes single-qubit depolarizing error, two-qubit depolarizing error,
    and symmetric readout bit-flip error.
    """
    noise_model = NoiseModel()
    if depolarizing_1q > 0.0:
        err_1q = depolarizing_error(depolarizing_1q, 1)
        noise_model.add_all_qubit_quantum_error(err_1q, ["u", "u1", "u2", "u3", "rx", "ry", "rz"])
    if depolarizing_2q > 0.0:
        err_2q = depolarizing_error(depolarizing_2q, 2)
        noise_model.add_all_qubit_quantum_error(err_2q, ["cx", "cz", "ecr"])
    if readout_error > 0.0:
        ro = ReadoutError(
            [
                [1.0 - readout_error, readout_error],
                [readout_error, 1.0 - readout_error],
            ]
        )
        noise_model.add_all_qubit_readout_error(ro)
    return noise_model


class LocalAerBackend(QuantumBackendAdapter):
    """Async Qiskit Aer simulator adapter supporting noiseless and noisy execution."""

    def __init__(
        self,
        backend_name: str = "qcloak_aer",
        num_qubits: int = 28,
        noise_model: NoiseModel | None = None,
        seed_simulator: int | None = None,
    ) -> None:
        self._name = backend_name
        self._num_qubits = num_qubits
        self._noise_model = noise_model
        self._seed_simulator = seed_simulator
        self._simulator = (
            AerSimulator(noise_model=noise_model) if noise_model is not None else AerSimulator()
        )
        self._jobs: dict[str, tuple[BackendJobStatus, dict[str, int]]] = {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def info(self) -> BackendInfo:
        return BackendInfo(
            name=self._name,
            backend_type="local_aer",
            num_qubits=self._num_qubits,
            is_simulator=True,
            has_noise_model=self._noise_model is not None,
        )

    def _run_sync(self, circuit: QuantumCircuit, shots: int) -> dict[str, int]:
        compiled = transpile(circuit, self._simulator, optimization_level=0)
        run_kwargs: dict[str, object] = {"shots": shots}
        if self._seed_simulator is not None:
            run_kwargs["seed_simulator"] = self._seed_simulator
        result = self._simulator.run(compiled, **run_kwargs).result()
        raw_counts = result.get_counts(compiled)
        return {str(k): int(v) for k, v in raw_counts.items()}

    async def submit(self, circuit: QuantumCircuit, shots: int = 1024) -> str:
        if circuit.num_qubits > self._num_qubits:
            raise ValueError(
                f"Circuit requires {circuit.num_qubits} qubits, "
                f"but backend '{self._name}' supports {self._num_qubits}."
            )
        job_id = f"aer-{uuid.uuid4().hex[:12]}"
        self._jobs[job_id] = (BackendJobStatus.RUNNING, {})
        try:
            counts = await asyncio.to_thread(self._run_sync, circuit, shots)
            self._jobs[job_id] = (BackendJobStatus.COMPLETED, counts)
        except Exception:
            self._jobs[job_id] = (BackendJobStatus.FAILED, {})
            raise
        return job_id

    async def status(self, backend_job_id: str) -> BackendJobStatus:
        if backend_job_id not in self._jobs:
            raise KeyError(f"Unknown Aer job ID: {backend_job_id}")
        return self._jobs[backend_job_id][0]

    async def result(self, backend_job_id: str) -> dict[str, int]:
        if backend_job_id not in self._jobs:
            raise KeyError(f"Unknown Aer job ID: {backend_job_id}")
        status, counts = self._jobs[backend_job_id]
        if status != BackendJobStatus.COMPLETED:
            raise RuntimeError(f"Job {backend_job_id} is not completed (status={status})")
        return dict(counts)
