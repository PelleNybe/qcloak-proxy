"""Qiskit BackendV2 & JobV1 drop-in plugin routing transparently to qcloak-proxy."""

from __future__ import annotations

import time
from typing import Any

import httpx
from qiskit import QuantumCircuit
from qiskit.circuit.library import CXGate, CZGate, HGate, RXGate, RYGate, RZGate, UGate, XGate
from qiskit.circuit.measure import Measure
from qiskit.circuit.reset import Reset
from qiskit.providers import BackendV2, JobStatus, JobV1, Options
from qiskit.qasm3 import dumps as qasm3_dumps
from qiskit.result import Result
from qiskit.result.models import ExperimentResult, ExperimentResultData
from qiskit.transpiler import Target

from qcloak_proxy import __version__
from qcloak_proxy.config import PrivacyProfile

_JOB_STATUS_MAP: dict[str, JobStatus] = {
    "PENDING": JobStatus.QUEUED,
    "RUNNING": JobStatus.RUNNING,
    "COMPLETED": JobStatus.DONE,
    "FAILED": JobStatus.ERROR,
    "CANCELLED": JobStatus.CANCELLED,
}


class QCloakJob(JobV1):
    """Qiskit JobV1 handle for one or more circuits submitted to qcloak-proxy."""

    def __init__(
        self,
        backend: QCloakBackend,
        job_ids: list[str],
        circuit_names: list[str],
        shots: int,
        client: httpx.Client,
    ) -> None:
        primary_id = job_ids[0] if len(job_ids) == 1 else ",".join(job_ids)
        super().__init__(backend, primary_id)
        self._job_ids = job_ids
        self._circuit_names = circuit_names
        self._shots = shots
        self._client = client

    def submit(self) -> None:
        """Jobs are submitted immediately in ``QCloakBackend.run``."""
        return None

    def status(self) -> JobStatus:
        """Query the proxy for the aggregated status of all circuits in this job."""
        statuses: list[JobStatus] = []
        for jid in self._job_ids:
            resp = self._client.get(f"/status/{jid}")
            resp.raise_for_status()
            raw = str(resp.json().get("status", "PENDING")).upper()
            statuses.append(_JOB_STATUS_MAP.get(raw, JobStatus.RUNNING))

        if any(s == JobStatus.ERROR for s in statuses):
            return JobStatus.ERROR
        if any(s == JobStatus.CANCELLED for s in statuses):
            return JobStatus.CANCELLED
        if all(s == JobStatus.DONE for s in statuses):
            return JobStatus.DONE
        if any(s == JobStatus.RUNNING for s in statuses):
            return JobStatus.RUNNING
        return JobStatus.QUEUED

    def result(self, timeout: float | None = None, wait: float = 0.05) -> Result:
        """Wait for completion and return a standard Qiskit ``Result`` with decoded counts."""
        start = time.monotonic()
        while True:
            current = self.status()
            if current == JobStatus.DONE:
                break
            if current in {JobStatus.ERROR, JobStatus.CANCELLED}:
                raise RuntimeError(f"QCloakJob {self._job_id} ended with status {current}")
            if timeout is not None and (time.monotonic() - start) > timeout:
                raise TimeoutError(f"Timed out waiting for QCloakJob {self._job_id}")
            time.sleep(wait)

        exp_results: list[ExperimentResult] = []
        for jid, cname in zip(self._job_ids, self._circuit_names, strict=True):
            resp = self._client.get(f"/result/{jid}")
            resp.raise_for_status()
            data = resp.json()
            counts = {str(k): round(float(v)) for k, v in data["counts"].items()}
            exp_results.append(
                ExperimentResult(
                    shots=self._shots,
                    success=True,
                    data=ExperimentResultData(counts=counts),
                    header={"name": cname},
                )
            )

        return Result(
            backend_name=self.backend().name,
            backend_version=__version__,
            qobj_id=self._job_id,
            job_id=self._job_id,
            success=True,
            results=exp_results,
        )

    def metrics(self, include_noise_sim: bool = False) -> list[dict[str, Any]]:
        """Retrieve Price-of-Privacy metrics for each circuit in this job."""
        reports: list[dict[str, Any]] = []
        for jid in self._job_ids:
            resp = self._client.get(
                f"/metrics/{jid}",
                params={"include_noise_sim": str(include_noise_sim).lower()},
            )
            resp.raise_for_status()
            reports.append(dict(resp.json()))
        return reports

    def cancel(self) -> bool:
        """Cancellation is not supported after remote dispatch."""
        return False


class QCloakBackend(BackendV2):
    """Standards-compliant Qiskit ``BackendV2`` routing to a ``qcloak-proxy`` server."""

    def __init__(
        self,
        proxy_url: str = "http://127.0.0.1:8000",
        backend_name: str = "qcloak_aer",
        num_qubits: int = 28,
        api_key: str | None = None,
        privacy_profile: PrivacyProfile = PrivacyProfile.MEDIUM,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(
            name=backend_name,
            description=f"qcloak-proxy Privacy Backend ({backend_name})",
            backend_version=__version__,
        )
        self._proxy_url = proxy_url.rstrip("/")
        self._backend_name = backend_name
        self._num_qubits = num_qubits
        self._privacy_profile = privacy_profile

        if client is not None:
            self._client = client
        else:
            headers: dict[str, str] = {"Accept": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            self._client = httpx.Client(
                base_url=self._proxy_url,
                headers=headers,
                timeout=60.0,
            )

        self._target = self._build_target(num_qubits)

    @staticmethod
    def _build_target(num_qubits: int) -> Target:
        target = Target(num_qubits=num_qubits)
        # Single-qubit basis gates across all qubits
        for gate in (UGate(0, 0, 0), RXGate(0), RYGate(0), RZGate(0), HGate(), XGate()):
            target.add_instruction(gate, {(q,): None for q in range(num_qubits)})
        target.add_instruction(Measure(), {(q,): None for q in range(num_qubits)})
        target.add_instruction(Reset(), {(q,): None for q in range(num_qubits)})
        # All-to-all 2-qubit connectivity (proxy handles logical permutation)
        pairs = {(i, j): None for i in range(num_qubits) for j in range(num_qubits) if i != j}
        if pairs:
            target.add_instruction(CXGate(), pairs)
            target.add_instruction(CZGate(), pairs)
        return target

    @property
    def target(self) -> Target:
        return self._target

    @property
    def max_circuits(self) -> int | None:
        return 64

    @classmethod
    def _default_options(cls) -> Options:
        return Options(
            shots=1024,
            privacy_profile=PrivacyProfile.MEDIUM,
            enable_cutting=False,
            max_subcircuit_qubits=3,
        )

    def run(
        self, run_input: QuantumCircuit | list[QuantumCircuit], **options: Any
    ) -> QCloakJob:
        """Obfuscate and execute circuit(s) through ``qcloak-proxy``."""
        circuits = [run_input] if isinstance(run_input, QuantumCircuit) else list(run_input)
        shots = int(options.get("shots", self.options.shots))
        profile = options.get("privacy_profile", self._privacy_profile)
        profile_str = profile.value if isinstance(profile, PrivacyProfile) else str(profile)
        enable_cutting = bool(options.get("enable_cutting", self.options.enable_cutting))
        max_sub_q = int(
            options.get("max_subcircuit_qubits", self.options.max_subcircuit_qubits)
        )

        job_ids: list[str] = []
        circuit_names: list[str] = []

        for idx, qc in enumerate(circuits):
            payload = {
                "qasm3": qasm3_dumps(qc),
                "shots": shots,
                "backend": self._backend_name,
                "privacy_profile": profile_str,
                "enable_cutting": enable_cutting,
                "max_subcircuit_qubits": max_sub_q,
            }
            resp = self._client.post("/submit", json=payload)
            resp.raise_for_status()
            job_ids.append(str(resp.json()["job_id"]))
            circuit_names.append(qc.name or f"circuit_{idx}")

        return QCloakJob(
            backend=self,
            job_ids=job_ids,
            circuit_names=circuit_names,
            shots=shots,
            client=self._client,
        )
