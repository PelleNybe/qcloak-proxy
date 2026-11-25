"""Phase 2 tests: SQLite WAL state store, FastAPI proxy endpoints, and CloudQuantumClient."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from qiskit import QuantumCircuit
from qiskit.qasm3 import dumps as qasm3_dumps

from qcloak_proxy.backends.base import BackendJobStatus
from qcloak_proxy.backends.cloud_client import CloudQuantumClient
from qcloak_proxy.config import CloudProviderType, PrivacyProfile, ProxySettings
from qcloak_proxy.server.api import create_app
from qcloak_proxy.server.state_store import LocalStateStore


def _bell_qasm3() -> str:
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])
    return qasm3_dumps(qc)


def test_sqlite_wal_persistence_across_restarts(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    store1 = LocalStateStore(db_path)

    with store1._connect() as conn:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert str(mode).lower() == "wal"

    app = create_app(settings=ProxySettings(db_path=db_path))
    with TestClient(app) as client:
        resp = client.post(
            "/submit",
            json={"qasm3": _bell_qasm3(), "shots": 1024, "privacy_profile": "high"},
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

    # Re-open a fresh store instance from disk
    store2 = LocalStateStore(db_path)
    record = store2.get_job(job_id)
    assert record is not None
    assert record.privacy_profile == PrivacyProfile.HIGH
    assert record.key_bundle is not None
    assert record.obfuscated_qasm != record.original_qasm


def test_fastapi_proxy_end_to_end_lifecycle(tmp_path: Path) -> None:
    db_path = tmp_path / "proxy.db"
    app = create_app(settings=ProxySettings(db_path=db_path))

    with TestClient(app) as client:
        ui = client.get("/")
        assert ui.status_code == 200
        assert "qcloak-proxy" in ui.text
        assert "Circuit Cloaking Auditor" in ui.text

        health = client.get("/health")
        assert health.status_code == 200
        backend_names = [b["name"] for b in health.json()["backends"]]
        assert "qcloak_aer" in backend_names
        assert "qcloak_aer_noisy" in backend_names

        submit = client.post(
            "/submit",
            json={
                "qasm3": _bell_qasm3(),
                "shots": 2048,
                "backend": "qcloak_aer",
                "privacy_profile": "medium",
            },
        )
        assert submit.status_code == 202
        job_id = submit.json()["job_id"]

        st = client.get(f"/status/{job_id}")
        assert st.status_code == 200
        assert st.json()["status"] == "COMPLETED"

        res = client.get(f"/result/{job_id}")
        assert res.status_code == 200
        probs = res.json()["probabilities"]
        assert probs.get("00", 0.0) + probs.get("11", 0.0) > 0.98

        metrics = client.get(f"/metrics/{job_id}?include_noise_sim=true")
        assert metrics.status_code == 200
        m_data = metrics.json()
        assert (
            m_data["overhead"]["obfuscated_gate_count"]
            >= m_data["overhead"]["original_gate_count"]
        )
        assert m_data["ideal_fidelity"]["hellinger_fidelity"] > 0.99
        assert m_data["noisy_fidelity"] is not None

        jobs_list = client.get("/jobs")
        assert jobs_list.status_code == 200
        assert any(j["job_id"] == job_id for j in jobs_list.json())

        dry_run = client.post(
            "/obfuscate",
            json={"qasm3": _bell_qasm3(), "privacy_profile": "high"},
        )
        assert dry_run.status_code == 200
        assert dry_run.json()["dummy_blocks_inserted"] >= 1
        assert "OPENQASM 3.0" in dry_run.json()["obfuscated_qasm3"]

        deleted = client.delete(f"/jobs/{job_id}")
        assert deleted.status_code == 204
        assert client.get(f"/status/{job_id}").status_code == 404


def test_encrypted_sqlite_at_rest(tmp_path: Path) -> None:
    db_path = tmp_path / "encrypted.db"
    app = create_app(
        settings=ProxySettings(
            db_path=db_path,
            state_encryption_key="super-secret-corax-passphrase",
        )
    )
    with TestClient(app) as client:
        resp = client.post("/submit", json={"qasm3": _bell_qasm3(), "shots": 512})
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        res = client.get(f"/result/{job_id}")
        assert res.status_code == 200

    # Verify raw SQLite row is encrypted on disk
    store_raw = LocalStateStore(db_path)
    with store_raw._connect() as conn:
        row = conn.execute(
            "SELECT original_qasm, key_bundle_json, decoded_counts_json "
            "FROM jobs WHERE job_id = ?;",
            (job_id,),
        ).fetchone()
        assert str(row["original_qasm"]).startswith("enc:")
        assert str(row["key_bundle_json"]).startswith("enc:")
        assert str(row["decoded_counts_json"]).startswith("enc:")

    # Verify store with key decrypts transparently
    store_dec = LocalStateStore(db_path, encryption_key="super-secret-corax-passphrase")
    rec = store_dec.get_job(job_id)
    assert rec is not None
    assert "OPENQASM" in rec.original_qasm
    assert rec.key_bundle is not None
    assert rec.decoded_counts is not None


def test_fastapi_proxy_bearer_auth(tmp_path: Path) -> None:
    app = create_app(
        settings=ProxySettings(db_path=tmp_path / "auth.db", proxy_api_key="secret-token")
    )
    with TestClient(app) as client:
        unauth = client.post("/submit", json={"qasm3": _bell_qasm3(), "shots": 512})
        assert unauth.status_code == 401

        auth = client.post(
            "/submit",
            json={"qasm3": _bell_qasm3(), "shots": 512},
            headers={"Authorization": "Bearer secret-token"},
        )
        assert auth.status_code == 202


@pytest.mark.parametrize(
    "provider_type",
    [CloudProviderType.QASM3_RUNNER, CloudProviderType.IBM_RUNTIME],
)
async def test_cloud_client_with_retries_and_mock_transport(
    provider_type: CloudProviderType,
) -> None:
    attempts = {"post": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/jobs":
            attempts["post"] += 1
            if attempts["post"] == 1:
                return httpx.Response(503, json={"error": "transient overload"})
            return httpx.Response(201, json={"id": "cloud-job-42"})
        if request.method == "GET" and request.url.path == "/jobs/cloud-job-42":
            return httpx.Response(200, json={"status": "COMPLETED"})
        if request.method == "GET" and request.url.path in {
            "/jobs/cloud-job-42/result",
            "/jobs/cloud-job-42/results",
        }:
            return httpx.Response(200, json={"counts": {"00": 510, "11": 514}})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = CloudQuantumClient(
        endpoint="https://quantum.example.com",
        api_token="tok-123",
        provider_type=provider_type,
        max_retries=2,
        transport=transport,
    )

    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])

    job_id = await client.submit(qc, shots=1024)
    assert job_id == "cloud-job-42"
    assert attempts["post"] == 2
    assert await client.status(job_id) == BackendJobStatus.COMPLETED
    counts = await client.result(job_id)
    assert counts == {"00": 510, "11": 514}
    await client.close()
