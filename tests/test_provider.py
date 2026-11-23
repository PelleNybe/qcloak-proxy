"""Phase 4 tests: Qiskit BackendV2, JobV1, QCloakProvider, and Typer CLI."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from qiskit import QuantumCircuit, transpile
from qiskit.providers import JobStatus
from typer.testing import CliRunner

from qcloak_proxy.cli import app as cli_app
from qcloak_proxy.config import PrivacyProfile, ProxySettings
from qcloak_proxy.provider import QCloakBackend, QCloakProvider
from qcloak_proxy.server.api import create_app


def test_qcloak_provider_and_backendv2_single_and_batch(tmp_path: Path) -> None:
    app = create_app(settings=ProxySettings(db_path=tmp_path / "provider.db"))

    with TestClient(app) as test_client:
        provider = QCloakProvider(
            proxy_url="http://testserver",
            privacy_profile=PrivacyProfile.MEDIUM,
            client=test_client,  # type: ignore[arg-type]
        )
        backends = provider.backends()
        assert any(b.name == "qcloak_aer" for b in backends)

        backend: QCloakBackend = provider.get_backend("qcloak_aer")

        bell = QuantumCircuit(2, 2, name="bell")
        bell.h(0)
        bell.cx(0, 1)
        bell.measure([0, 1], [0, 1])

        transpiled = transpile(bell, backend)
        job = backend.run(transpiled, shots=2048)
        assert job.status() in {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.DONE}

        result = job.result(timeout=10.0)
        assert result.success
        counts = result.get_counts()
        total = sum(counts.values())
        assert (counts.get("00", 0) + counts.get("11", 0)) / total > 0.98

        # Batch execution
        ghz = QuantumCircuit(3, 3, name="ghz")
        ghz.h(0)
        ghz.cx(0, 1)
        ghz.cx(1, 2)
        ghz.measure([0, 1, 2], [0, 1, 2])

        batch_job = backend.run([bell, ghz], shots=1024)
        batch_res = batch_job.result(timeout=10.0)
        c0 = batch_res.get_counts(0)
        c1 = batch_res.get_counts(1)
        assert sum(c0.values()) > 0
        assert (c1.get("000", 0) + c1.get("111", 0)) / sum(c1.values()) > 0.98

        metrics_list = batch_job.metrics(include_noise_sim=False)
        assert len(metrics_list) == 2
        assert metrics_list[0]["overhead"]["obfuscated_gate_count"] >= 1

        # Circuit cutting via QCloakBackend.run(..., enable_cutting=True)
        cut_job = backend.run(ghz, shots=1024, enable_cutting=True, max_subcircuit_qubits=2)
        cut_res = cut_job.result(timeout=20.0)
        cut_counts = cut_res.get_counts()
        assert sum(cut_counts.values()) > 0


def test_cli_benchmark_cloak_and_jobs(tmp_path: Path) -> None:
    runner = CliRunner()
    bench = runner.invoke(cli_app, ["benchmark", "--qubits", "3", "--shots", "512"])
    assert bench.exit_code == 0
    assert "Price of Privacy Benchmark" in bench.output

    qasm_file = tmp_path / "bell.qasm"
    qasm_file.write_text(
        'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nbit[2] c;\n'
        "h q[0];\ncx q[0], q[1];\nc = measure q;\n",
        encoding="utf-8",
    )
    out_file = tmp_path / "cloaked.qasm"
    cloak_res = runner.invoke(
        cli_app, ["cloak", str(qasm_file), "--profile", "high", "--output", str(out_file)]
    )
    assert cloak_res.exit_code == 0
    assert out_file.exists()
    assert "Dummy blocks:" in cloak_res.output

    jobs_res = runner.invoke(cli_app, ["jobs", "--db-path", str(tmp_path / "missing.db")])
    assert jobs_res.exit_code == 0
