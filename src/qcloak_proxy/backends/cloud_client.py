"""Production async HTTP/2 client adapter for cloud quantum backends."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from qiskit import QuantumCircuit
from qiskit.qasm3 import dumps as qasm3_dumps

from qcloak_proxy.backends.base import BackendInfo, BackendJobStatus, QuantumBackendAdapter
from qcloak_proxy.config import CloudProviderType

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

_STATUS_MAP: dict[str, BackendJobStatus] = {
    "QUEUED": BackendJobStatus.PENDING,
    "PENDING": BackendJobStatus.PENDING,
    "VALIDATING": BackendJobStatus.PENDING,
    "RUNNING": BackendJobStatus.RUNNING,
    "IN_PROGRESS": BackendJobStatus.RUNNING,
    "COMPLETED": BackendJobStatus.COMPLETED,
    "DONE": BackendJobStatus.COMPLETED,
    "FAILED": BackendJobStatus.FAILED,
    "ERROR": BackendJobStatus.FAILED,
    "CANCELLED": BackendJobStatus.CANCELLED,
    "CANCELED": BackendJobStatus.CANCELLED,
}


class CloudQuantumClient(QuantumBackendAdapter):
    """Async HTTP/2 client adapter for IBM Quantum Runtime & generic OpenQASM 3 runners."""

    def __init__(
        self,
        endpoint: str,
        api_token: str | None = None,
        backend_name: str = "qcloak_cloud",
        remote_backend_id: str = "ibm_brisbane",
        provider_type: CloudProviderType = CloudProviderType.QASM3_RUNNER,
        num_qubits: int = 127,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._api_token = api_token
        self._name = backend_name
        self._remote_backend_id = remote_backend_id
        self._provider_type = provider_type
        self._num_qubits = num_qubits
        self._max_retries = max_retries

        headers: dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "qcloak-proxy/0.1.0",
        }
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        self._client = httpx.AsyncClient(
            base_url=self._endpoint,
            headers=headers,
            http2=True,
            timeout=timeout_seconds,
            verify=True,
            transport=transport,
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def info(self) -> BackendInfo:
        return BackendInfo(
            name=self._name,
            backend_type=f"cloud:{self._provider_type.value}",
            num_qubits=self._num_qubits,
            is_simulator=False,
            has_noise_model=True,
        )

    async def _request_with_retries(
        self, method: str, path: str, json_payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.request(method, path, json=json_payload)
                if response.status_code in _RETRYABLE_STATUS_CODES and attempt < self._max_retries:
                    await asyncio.sleep(min(2.0**attempt * 0.25, 4.0))
                    continue
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError(f"Expected JSON object from cloud API, got {type(data)}")
                return data
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(min(2.0**attempt * 0.25, 4.0))
                    continue
                raise
        assert last_exc is not None
        raise last_exc

    async def submit(self, circuit: QuantumCircuit, shots: int = 1024) -> str:
        qasm3_source = qasm3_dumps(circuit)
        if self._provider_type == CloudProviderType.IBM_RUNTIME:
            payload: dict[str, Any] = {
                "program_id": "sampler",
                "backend": self._remote_backend_id,
                "params": {
                    "pubs": [[qasm3_source, None, shots]],
                    "version": 2,
                },
            }
        else:
            payload = {
                "backend": self._remote_backend_id,
                "qasm3": qasm3_source,
                "shots": shots,
            }

        data = await self._request_with_retries("POST", "/jobs", json_payload=payload)
        job_id = data.get("id") or data.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise ValueError(f"Cloud API response missing job ID: {data}")
        return job_id

    async def status(self, backend_job_id: str) -> BackendJobStatus:
        data = await self._request_with_retries("GET", f"/jobs/{backend_job_id}")
        raw_status = str(data.get("status") or data.get("state", {}).get("status") or "PENDING")
        return _STATUS_MAP.get(raw_status.upper(), BackendJobStatus.RUNNING)

    async def result(self, backend_job_id: str) -> dict[str, int]:
        path = (
            f"/jobs/{backend_job_id}/results"
            if self._provider_type == CloudProviderType.IBM_RUNTIME
            else f"/jobs/{backend_job_id}/result"
        )
        data = await self._request_with_retries("GET", path)

        if "counts" in data and isinstance(data["counts"], dict):
            return {str(k): int(v) for k, v in data["counts"].items()}

        # Support IBM Runtime SamplerV2-style quasi/bitstring results if returned
        results_list = data.get("results")
        if isinstance(results_list, list) and results_list:
            first = results_list[0]
            if isinstance(first, dict):
                counts = first.get("data", {}).get("c", {}).get("counts") or first.get("counts")
                if isinstance(counts, dict):
                    return {str(k): int(v) for k, v in counts.items()}

        raise ValueError(f"Unable to parse counts from cloud result payload: {data}")

    async def cancel(self, backend_job_id: str) -> bool:
        try:
            await self._request_with_retries("POST", f"/jobs/{backend_job_id}/cancel")
            return True
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        await self._client.aclose()
