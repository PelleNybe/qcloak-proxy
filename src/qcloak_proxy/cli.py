"""Typer CLI for launching qcloak-proxy, inspecting jobs, and running privacy benchmarks."""

from __future__ import annotations

from pathlib import Path

import typer
import uvicorn
from qiskit import QuantumCircuit
from qiskit.qasm3 import dumps as qasm3_dumps
from qiskit.qasm3 import loads as qasm3_loads
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from qcloak_proxy.config import PrivacyProfile, ProxySettings
from qcloak_proxy.metrics import compute_circuit_overhead, evaluate_privacy_metrics
from qcloak_proxy.obfuscation.pipeline import ObfuscationPipeline
from qcloak_proxy.server.api import create_app
from qcloak_proxy.server.state_store import LocalStateStore

app = typer.Typer(
    name="qcloak-proxy",
    help="Zero-trust Privacy Proxy for cloud-based quantum computers (Corax CoLAB).",
    no_args_is_help=True,
)
console = Console()


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host address."),
    port: int = typer.Option(8000, help="Bind port."),
    db_path: Path = typer.Option(Path("qcloak_proxy.db"), help="Local SQLite DB path."),
    privacy_profile: PrivacyProfile = typer.Option(
        PrivacyProfile.MEDIUM, help="Default privacy profile."
    ),
) -> None:
    """Launch the local qcloak-proxy FastAPI server."""
    settings = ProxySettings(
        host=host,
        port=port,
        db_path=db_path,
        privacy_profile=privacy_profile,
    )
    fastapi_app = create_app(settings=settings)
    console.print(
        f"[bold green]Starting qcloak-proxy[/bold green] on "
        f"http://{host}:{port} (profile={privacy_profile.value}, db={db_path})"
    )
    uvicorn.run(fastapi_app, host=host, port=port)


@app.command()
def jobs(
    db_path: Path = typer.Option(Path("qcloak_proxy.db"), help="Local SQLite DB path."),
    limit: int = typer.Option(20, help="Maximum number of recent jobs to display."),
) -> None:
    """Inspect locally stored job records and privacy profiles."""
    if not db_path.exists():
        console.print(f"[yellow]No state database found at {db_path}[/yellow]")
        raise typer.Exit(code=0)

    store = LocalStateStore(db_path)
    records = store.list_jobs(limit=limit)

    table = Table(title=f"qcloak-proxy Jobs ({db_path})")
    table.add_column("Job ID", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Backend")
    table.add_column("Profile")
    table.add_column("Shots", justify="right")
    table.add_column("Created At")

    for rec in records:
        table.add_row(
            rec.job_id,
            rec.status.value,
            rec.backend_name,
            rec.privacy_profile.value,
            str(rec.shots),
            rec.created_at,
        )

    console.print(table)


@app.command()
def benchmark(
    qubits: int = typer.Option(4, min=2, max=8, help="Number of qubits for GHZ benchmark."),
    shots: int = typer.Option(4096, min=256, help="Shots per Aer simulation."),
) -> None:
    """Run a local 'Price of Privacy' benchmark across low, medium, and high profiles."""
    qc = QuantumCircuit(qubits, qubits)
    qc.h(0)
    for i in range(qubits - 1):
        qc.cx(i, i + 1)
    qc.measure(range(qubits), range(qubits))

    table = Table(title=f"Price of Privacy Benchmark ({qubits}-Qubit GHZ, {shots} shots)")
    table.add_column("Profile", style="cyan")
    table.add_column("Depth (Orig -> Obf)", justify="right")
    table.add_column("Gates (Orig -> Obf)", justify="right")
    table.add_column("2Q Gates", justify="right")
    table.add_column("Ideal TVD", justify="right")
    table.add_column("Ideal Hellinger", justify="right")
    table.add_column("Noisy TVD", justify="right")
    table.add_column("Noisy Hellinger", justify="right")

    for profile in (PrivacyProfile.LOW, PrivacyProfile.MEDIUM, PrivacyProfile.HIGH):
        pipeline = ObfuscationPipeline(profile=profile)
        cloaked, key_bundle = pipeline.obfuscate(qc)
        report = evaluate_privacy_metrics(qc, cloaked, key_bundle, shots=shots)
        ov = report.overhead
        ideal = report.ideal_fidelity
        noisy = report.noisy_fidelity

        table.add_row(
            profile.value,
            f"{ov.original_depth} -> {ov.obfuscated_depth} (+{ov.depth_increase_pct}%)",
            f"{ov.original_gate_count} -> {ov.obfuscated_gate_count} (+{ov.gate_increase_pct}%)",
            f"{ov.original_two_qubit_gates} -> {ov.obfuscated_two_qubit_gates}",
            f"{ideal.total_variation_distance:.4f}" if ideal else "-",
            f"{ideal.hellinger_fidelity:.4f}" if ideal else "-",
            f"{noisy.total_variation_distance:.4f}" if noisy else "-",
            f"{noisy.hellinger_fidelity:.4f}" if noisy else "-",
        )

    console.print(table)


@app.command()
def cloak(
    input_file: Path = typer.Argument(..., exists=True, help="Path to OpenQASM 3/2 file."),
    profile: PrivacyProfile = typer.Option(
        PrivacyProfile.MEDIUM, help="Obfuscation privacy profile."
    ),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write cloaked QASM3 to file."),
) -> None:
    """Cloak a local OpenQASM 3/2 file and inspect the structural overhead."""
    source = input_file.read_text(encoding="utf-8")
    try:
        qc = qasm3_loads(source)
    except Exception:
        qc = QuantumCircuit.from_qasm_str(source)

    pipeline = ObfuscationPipeline(profile=profile)
    cloaked, key_bundle = pipeline.obfuscate(qc)
    cloaked_qasm = qasm3_dumps(cloaked)
    ov = compute_circuit_overhead(qc, cloaked)

    if output is not None:
        output.write_text(cloaked_qasm, encoding="utf-8")
        console.print(f"[green]Wrote cloaked OpenQASM 3 to {output}[/green]")
    else:
        console.print(Panel(cloaked_qasm, title=f"Cloaked OpenQASM 3 ({profile.value})"))

    console.print(
        f"Depth: {ov.original_depth} -> {ov.obfuscated_depth} (+{ov.depth_increase_pct}%) | "
        f"Gates: {ov.original_gate_count} -> {ov.obfuscated_gate_count} "
        f"(+{ov.gate_increase_pct}%) | "
        f"Dummy blocks: {key_bundle.dummy_blocks_inserted}"
    )


@app.command()
def purge(
    job_id: str = typer.Argument(..., help="Job ID to delete from local state store."),
    db_path: Path = typer.Option(Path("qcloak_proxy.db"), help="Local SQLite DB path."),
) -> None:
    """Purge a job and its local decoding keys from the SQLite database."""
    if not db_path.exists():
        console.print(f"[yellow]No state database found at {db_path}[/yellow]")
        raise typer.Exit(code=1)
    store = LocalStateStore(db_path)
    if store.delete_job(job_id):
        console.print(f"[green]Purged job '{job_id}' and its local keys.[/green]")
    else:
        console.print(f"[red]Job '{job_id}' not found.[/red]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
