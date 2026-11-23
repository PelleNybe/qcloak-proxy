"""FastAPI Privacy Proxy server exposing /submit, /status, /result, /metrics, /health."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from qiskit import QuantumCircuit
from qiskit.qasm3 import dumps as qasm3_dumps
from qiskit.qasm3 import loads as qasm3_loads

from qcloak_proxy import __version__
from qcloak_proxy.backends.base import BackendInfo, BackendJobStatus, QuantumBackendAdapter
from qcloak_proxy.backends.cloud_client import CloudQuantumClient
from qcloak_proxy.backends.local_aer import LocalAerBackend, build_realistic_noise_model
from qcloak_proxy.config import PrivacyProfile, ProxySettings
from qcloak_proxy.metrics import (
    CircuitOverheadMetrics,
    PrivacyMetricsReport,
    compute_circuit_overhead,
    counts_to_probabilities,
    evaluate_privacy_metrics,
)
from qcloak_proxy.obfuscation.cutter import CircuitCutter
from qcloak_proxy.obfuscation.pipeline import ObfuscationPipeline
from qcloak_proxy.server.state_store import JobRecord, LocalStateStore, _utc_now_iso


class SubmitJobRequest(BaseModel):
    """Request payload for submitting an OpenQASM 3 (or QASM 2) circuit."""

    qasm3: str = Field(..., min_length=1, description="OpenQASM 3 (or QASM 2) circuit source.")
    shots: int = Field(default=1024, ge=1, le=1_000_000)
    backend: str | None = Field(default=None, description="Target backend name.")
    privacy_profile: PrivacyProfile | None = Field(default=None)
    enable_cutting: bool | None = Field(default=None)
    max_subcircuit_qubits: int | None = Field(default=None, ge=1)


class SubmitJobResponse(BaseModel):
    """Response returned immediately after local cloaking & dispatch."""

    job_id: str
    status: BackendJobStatus
    backend: str
    privacy_profile: PrivacyProfile
    cutting_enabled: bool


class JobStatusResponse(BaseModel):
    """Status response for a submitted job."""

    job_id: str
    status: BackendJobStatus
    backend: str
    privacy_profile: PrivacyProfile
    created_at: str
    updated_at: str
    error_message: str | None = None


class JobResultResponse(BaseModel):
    """Decoded execution results for a completed job."""

    job_id: str
    status: BackendJobStatus
    backend: str
    shots: int
    counts: dict[str, int | float]
    probabilities: dict[str, float]


class HealthResponse(BaseModel):
    """Health check and registered backend inventory."""

    status: str
    version: str
    backends: list[BackendInfo]


class JobSummary(BaseModel):
    """Compact summary of a stored job."""

    job_id: str
    status: BackendJobStatus
    backend: str
    privacy_profile: PrivacyProfile
    shots: int
    created_at: str


class ObfuscateDryRunRequest(BaseModel):
    """Request payload for dry-run circuit cloaking without execution."""

    qasm3: str = Field(..., min_length=1, description="OpenQASM 3 (or QASM 2) circuit source.")
    privacy_profile: PrivacyProfile = Field(default=PrivacyProfile.MEDIUM)


class ObfuscateDryRunResponse(BaseModel):
    """Cloaked OpenQASM 3 and overhead metrics without executing on a backend."""

    obfuscated_qasm3: str
    privacy_profile: PrivacyProfile
    overhead: CircuitOverheadMetrics
    dummy_blocks_inserted: int


def _parse_qasm(qasm_source: str) -> QuantumCircuit:
    """Parse OpenQASM 3 source, falling back to OpenQASM 2 if needed."""
    try:
        return qasm3_loads(qasm_source)
    except Exception as qasm3_err:
        try:
            return QuantumCircuit.from_qasm_str(qasm_source)
        except Exception as qasm2_err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid OpenQASM 3/2 circuit: {qasm3_err} | {qasm2_err}",
            ) from qasm3_err


def _build_default_backends(settings: ProxySettings) -> dict[str, QuantumBackendAdapter]:
    """Instantiate local Aer (ideal + noisy) and optional cloud backend adapters."""
    backends: dict[str, QuantumBackendAdapter] = {
        "qcloak_aer": LocalAerBackend(backend_name="qcloak_aer"),
        "qcloak_aer_noisy": LocalAerBackend(
            backend_name="qcloak_aer_noisy",
            noise_model=build_realistic_noise_model(
                depolarizing_1q=settings.aer_noise_depolarizing_1q,
                depolarizing_2q=settings.aer_noise_depolarizing_2q,
                readout_error=settings.aer_noise_readout_error,
            ),
        ),
    }
    if settings.cloud_endpoint:
        backends["qcloak_cloud"] = CloudQuantumClient(
            endpoint=settings.cloud_endpoint,
            api_token=settings.cloud_api_token,
            backend_name="qcloak_cloud",
            provider_type=settings.cloud_provider_type,
            timeout_seconds=settings.cloud_timeout_seconds,
            max_retries=settings.cloud_max_retries,
        )
    return backends


def create_app(
    settings: ProxySettings | None = None,
    backends: dict[str, QuantumBackendAdapter] | None = None,
) -> FastAPI:
    """Create and configure the FastAPI Privacy Proxy application."""
    cfg = settings or ProxySettings()
    store = LocalStateStore(cfg.db_path, encryption_key=cfg.state_encryption_key)
    backend_registry: dict[str, QuantumBackendAdapter] = (
        dict(backends) if backends is not None else _build_default_backends(cfg)
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        for adapter in backend_registry.values():
            await adapter.close()

    app = FastAPI(
        title="qcloak-proxy",
        version=__version__,
        description=(
            "Zero-trust Privacy Proxy for cloud-based quantum computers by Corax CoLAB. "
            "Cloaks circuits locally and decodes results on-premise."
        ),
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.store = store
    app.state.backends = backend_registry

    if cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    async def verify_auth(authorization: str | None = Header(default=None)) -> None:
        if cfg.proxy_api_key is None:
            return
        expected = f"Bearer {cfg.proxy_api_key}"
        if authorization != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing proxy Bearer token.",
            )

    def _get_backend(name: str | None) -> QuantumBackendAdapter:
        target = name or cfg.default_backend
        if target not in backend_registry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown backend '{target}'. Available: {sorted(backend_registry)}",
            )
        return backend_registry[target]

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=__version__,
            backends=[b.info for b in backend_registry.values()],
        )

    @app.post(
        "/obfuscate",
        response_model=ObfuscateDryRunResponse,
        dependencies=[Depends(verify_auth)],
    )
    async def obfuscate_dry_run(req: ObfuscateDryRunRequest) -> ObfuscateDryRunResponse:
        """Cloak a circuit and return the outbound OpenQASM 3 + overhead without executing."""
        circuit = _parse_qasm(req.qasm3)
        pipeline = ObfuscationPipeline(profile=req.privacy_profile)
        cloaked, key_bundle = pipeline.obfuscate(circuit)
        return ObfuscateDryRunResponse(
            obfuscated_qasm3=qasm3_dumps(cloaked),
            privacy_profile=req.privacy_profile,
            overhead=compute_circuit_overhead(circuit, cloaked),
            dummy_blocks_inserted=key_bundle.dummy_blocks_inserted,
        )

    @app.delete(
        "/jobs/{job_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(verify_auth)],
    )
    async def delete_job(job_id: str) -> None:
        """Purge a job and its local decoding keys from the SQLite state store."""
        if not store.delete_job(job_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    @app.get("/jobs", response_model=list[JobSummary], dependencies=[Depends(verify_auth)])
    async def list_jobs(limit: int = Query(default=50, ge=1, le=500)) -> list[JobSummary]:
        records = store.list_jobs(limit=limit)
        return [
            JobSummary(
                job_id=r.job_id,
                status=r.status,
                backend=r.backend_name,
                privacy_profile=r.privacy_profile,
                shots=r.shots,
                created_at=r.created_at,
            )
            for r in records
        ]

    @app.post(
        "/submit",
        response_model=SubmitJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[Depends(verify_auth)],
    )
    async def submit_job(req: SubmitJobRequest) -> SubmitJobResponse:
        circuit = _parse_qasm(req.qasm3)
        backend = _get_backend(req.backend)
        profile = req.privacy_profile or cfg.privacy_profile
        use_cutting = (
            req.enable_cutting if req.enable_cutting is not None else cfg.enable_cutting
        )
        max_sub_q = req.max_subcircuit_qubits or cfg.max_subcircuit_qubits

        job_id = f"qcloak-{uuid.uuid4().hex[:12]}"
        now = _utc_now_iso()

        if use_cutting:
            cutter = CircuitCutter(
                max_subcircuit_qubits=max_sub_q,
                privacy_profile=profile,
            )
            try:
                cut_result = await cutter.cut_and_reconstruct_distribution(
                    circuit,
                    backends=[backend],
                    total_shots=req.shots,
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Circuit cutting failed: {exc}",
                ) from exc

            overhead = compute_circuit_overhead(
                circuit,
                circuit,
                cutting_sampling_overhead=cut_result.metadata.sampling_overhead,
            )
            record = JobRecord(
                job_id=job_id,
                status=BackendJobStatus.COMPLETED,
                backend_name=backend.name,
                privacy_profile=profile,
                shots=req.shots,
                created_at=now,
                updated_at=now,
                original_qasm=req.qasm3,
                obfuscated_qasm=req.qasm3,
                cutting_metadata=asdict(cut_result.metadata),
                raw_counts=cut_result.counts,
                decoded_counts=dict(cut_result.counts),
                metrics=PrivacyMetricsReport(overhead=overhead),
            )
            store.create_job(record)
            return SubmitJobResponse(
                job_id=job_id,
                status=BackendJobStatus.COMPLETED,
                backend=backend.name,
                privacy_profile=profile,
                cutting_enabled=True,
            )

        pipeline = ObfuscationPipeline(profile=profile)
        cloaked_circuit, key_bundle = pipeline.obfuscate(circuit)
        cloaked_qasm = qasm3_dumps(cloaked_circuit)
        overhead = compute_circuit_overhead(circuit, cloaked_circuit)

        record = JobRecord(
            job_id=job_id,
            status=BackendJobStatus.PENDING,
            backend_name=backend.name,
            privacy_profile=profile,
            shots=req.shots,
            created_at=now,
            updated_at=now,
            original_qasm=req.qasm3,
            obfuscated_qasm=cloaked_qasm,
            key_bundle=key_bundle,
            metrics=PrivacyMetricsReport(overhead=overhead),
        )
        store.create_job(record)

        try:
            backend_job_id = await backend.submit(cloaked_circuit, shots=req.shots)
            remote_status = await backend.status(backend_job_id)
            store.update_status(job_id, remote_status, backend_job_id=backend_job_id)
        except Exception as exc:
            store.update_status(job_id, BackendJobStatus.FAILED, error_message=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Backend execution failed: {exc}",
            ) from exc

        return SubmitJobResponse(
            job_id=job_id,
            status=remote_status,
            backend=backend.name,
            privacy_profile=profile,
            cutting_enabled=False,
        )

    @app.get(
        "/status/{job_id}",
        response_model=JobStatusResponse,
        dependencies=[Depends(verify_auth)],
    )
    async def get_status(job_id: str) -> JobStatusResponse:
        record = store.get_job(job_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

        if (
            record.status in {BackendJobStatus.PENDING, BackendJobStatus.RUNNING}
            and record.backend_job_id
        ):
            backend = backend_registry.get(record.backend_name)
            if backend is not None:
                remote_status = await backend.status(record.backend_job_id)
                if remote_status != record.status:
                    store.update_status(job_id, remote_status)
                    record.status = remote_status

        return JobStatusResponse(
            job_id=record.job_id,
            status=record.status,
            backend=record.backend_name,
            privacy_profile=record.privacy_profile,
            created_at=record.created_at,
            updated_at=record.updated_at,
            error_message=record.error_message,
        )

    @app.get(
        "/result/{job_id}",
        response_model=JobResultResponse,
        dependencies=[Depends(verify_auth)],
    )
    async def get_result(job_id: str) -> JobResultResponse:
        record = store.get_job(job_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

        if record.status == BackendJobStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=record.error_message or "Job failed.",
            )

        if record.decoded_counts is not None:
            return JobResultResponse(
                job_id=record.job_id,
                status=record.status,
                backend=record.backend_name,
                shots=record.shots,
                counts=record.decoded_counts,
                probabilities=counts_to_probabilities(record.decoded_counts),
            )

        if not record.backend_job_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Job has no backend execution ID.",
            )

        backend = _get_backend(record.backend_name)
        remote_status = await backend.status(record.backend_job_id)
        if remote_status != BackendJobStatus.COMPLETED:
            store.update_status(job_id, remote_status)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Job is not yet completed (status={remote_status.value}).",
            )

        raw_counts = await backend.result(record.backend_job_id)
        if record.key_bundle is not None:
            decoded = ObfuscationPipeline.decode_counts(raw_counts, record.key_bundle)
        else:
            decoded = dict(raw_counts)

        store.save_results(job_id, raw_counts=raw_counts, decoded_counts=decoded)
        return JobResultResponse(
            job_id=record.job_id,
            status=BackendJobStatus.COMPLETED,
            backend=record.backend_name,
            shots=record.shots,
            counts=decoded,
            probabilities=counts_to_probabilities(decoded),
        )

    @app.get(
        "/metrics/{job_id}",
        response_model=PrivacyMetricsReport,
        dependencies=[Depends(verify_auth)],
    )
    async def get_metrics(
        job_id: str,
        include_noise_sim: bool = Query(default=False),
    ) -> PrivacyMetricsReport:
        record = store.get_job(job_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

        if include_noise_sim and record.key_bundle is not None:
            orig_qc = _parse_qasm(record.original_qasm)
            obf_qc = _parse_qasm(record.obfuscated_qasm)
            cutting_ov = (
                float(record.cutting_metadata["sampling_overhead"])
                if record.cutting_metadata and "sampling_overhead" in record.cutting_metadata
                else None
            )
            report = evaluate_privacy_metrics(
                orig_qc,
                obf_qc,
                record.key_bundle,
                shots=min(record.shots, 4096),
                depolarizing_1q=cfg.aer_noise_depolarizing_1q,
                depolarizing_2q=cfg.aer_noise_depolarizing_2q,
                readout_error=cfg.aer_noise_readout_error,
                cutting_sampling_overhead=cutting_ov,
            )
            store.save_metrics(job_id, report)
            return report

        if record.metrics is not None:
            return record.metrics

        orig_qc = _parse_qasm(record.original_qasm)
        obf_qc = _parse_qasm(record.obfuscated_qasm)
        overhead = compute_circuit_overhead(orig_qc, obf_qc)
        report = PrivacyMetricsReport(overhead=overhead)
        store.save_metrics(job_id, report)
        return report

    return app


def create_default_app() -> FastAPI:
    """Entrypoint factory for uvicorn."""
    return create_app()
