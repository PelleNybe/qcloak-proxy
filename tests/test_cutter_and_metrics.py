"""Phase 3 tests: Circuit cutting (qiskit-addon-cutting) and Price-of-Privacy metrics."""

from __future__ import annotations

from qiskit import QuantumCircuit
from qiskit.quantum_info import PauliList, Statevector

from qcloak_proxy.backends.local_aer import LocalAerBackend
from qcloak_proxy.config import PrivacyProfile
from qcloak_proxy.metrics import (
    compute_tvd,
    counts_to_probabilities,
    evaluate_privacy_metrics,
)
from qcloak_proxy.obfuscation.cutter import CircuitCutter
from qcloak_proxy.obfuscation.pipeline import ObfuscationPipeline


async def test_circuit_cutting_expectation_values_multi_backend() -> None:
    # 4-qubit circuit with two weakly coupled Bell pairs
    qc = QuantumCircuit(4)
    qc.h(0)
    qc.cx(0, 1)
    qc.h(2)
    qc.cx(2, 3)
    qc.cz(1, 2)

    observables = PauliList(["ZZII", "IIZZ", "ZIIZ"])
    sv = Statevector.from_instruction(qc)
    exact_expvals = [float(sv.expectation_value(obs).real) for obs in observables]

    backend_a = LocalAerBackend(backend_name="aer_a", seed_simulator=11)
    backend_b = LocalAerBackend(backend_name="aer_b", seed_simulator=22)

    cutter = CircuitCutter(
        max_subcircuit_qubits=2,
        num_samples=250,
        shots_per_subexperiment=2048,
        privacy_profile=PrivacyProfile.LOW,
        seed=42,
    )
    cut_expvals, metadata = await cutter.cut_and_evaluate(
        qc, observables=observables, backends=[backend_a, backend_b]
    )

    assert metadata.num_partitions >= 2
    assert metadata.num_subexperiments > 0
    for exact, est in zip(exact_expvals, cut_expvals, strict=True):
        assert abs(exact - est) < 0.15


async def test_circuit_cutting_distribution_reconstruction() -> None:
    qc = QuantumCircuit(3)
    qc.h(0)
    qc.cx(0, 1)
    qc.cx(1, 2)

    sv = Statevector.from_instruction(qc)
    exact_probs = {k: float(v) for k, v in sv.probabilities_dict().items()}

    backend = LocalAerBackend(backend_name="aer_cut", seed_simulator=7)
    cutter = CircuitCutter(
        max_subcircuit_qubits=2,
        num_samples=250,
        shots_per_subexperiment=2048,
        privacy_profile=PrivacyProfile.LOW,
        seed=99,
    )
    res = await cutter.cut_and_reconstruct_distribution(qc, backends=[backend], total_shots=4096)

    tvd = compute_tvd(exact_probs, res.probabilities)
    assert tvd < 0.12
    assert sum(res.counts.values()) > 0


def test_metrics_overhead_and_noisy_fidelity() -> None:
    qc = QuantumCircuit(4, 4)
    qc.h(0)
    for i in range(3):
        qc.cx(i, i + 1)
    qc.measure(range(4), range(4))

    pipeline = ObfuscationPipeline(profile=PrivacyProfile.HIGH, seed=123)
    cloaked, key_bundle = pipeline.obfuscate(qc)

    report = evaluate_privacy_metrics(
        qc,
        cloaked,
        key_bundle,
        shots=4096,
        depolarizing_1q=0.002,
        depolarizing_2q=0.02,
        readout_error=0.02,
        seed=42,
    )

    assert report.overhead.depth_increase_abs > 0
    assert report.overhead.gate_increase_pct > 0.0
    assert report.ideal_fidelity is not None
    assert report.noisy_fidelity is not None
    assert report.ideal_fidelity.hellinger_fidelity > 0.99
    assert (
        report.noisy_fidelity.total_variation_distance
        > report.ideal_fidelity.total_variation_distance
    )
    assert counts_to_probabilities({"00": 50, "11": 50}) == {"00": 0.5, "11": 0.5}
