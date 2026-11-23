"""Price-of-Privacy metrics: circuit overhead, TVD, Hellinger fidelity, and noise impact."""

from __future__ import annotations

import math
from collections.abc import Mapping

from pydantic import BaseModel
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator

from qcloak_proxy.backends.local_aer import build_realistic_noise_model
from qcloak_proxy.obfuscation.pipeline import ObfuscationKeyBundle, ObfuscationPipeline


class CircuitOverheadMetrics(BaseModel):
    """Structural overhead introduced by circuit obfuscation and/or cutting."""

    original_depth: int
    obfuscated_depth: int
    depth_increase_abs: int
    depth_increase_pct: float

    original_gate_count: int
    obfuscated_gate_count: int
    gate_increase_abs: int
    gate_increase_pct: float

    original_two_qubit_gates: int
    obfuscated_two_qubit_gates: int
    two_qubit_increase_abs: int
    two_qubit_increase_pct: float

    cutting_sampling_overhead: float | None = None


class FidelityMetrics(BaseModel):
    """Statistical distance & fidelity metrics between two probability distributions."""

    total_variation_distance: float
    hellinger_fidelity: float
    kl_divergence: float


class PrivacyMetricsReport(BaseModel):
    """Combined overhead and fidelity report for a cloaked quantum job."""

    overhead: CircuitOverheadMetrics
    ideal_fidelity: FidelityMetrics | None = None
    noisy_fidelity: FidelityMetrics | None = None


def counts_to_probabilities(counts: Mapping[str, int | float]) -> dict[str, float]:
    """Normalize a counts dictionary into a probability distribution."""
    total = float(sum(counts.values()))
    if total <= 0.0:
        return {}
    return {k: float(v) / total for k, v in counts.items()}


def compute_tvd(p: Mapping[str, float], q: Mapping[str, float]) -> float:
    """Compute Total Variation Distance: ``0.5 * sum_x |p(x) - q(x)|``."""
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys)


def compute_hellinger_fidelity(p: Mapping[str, float], q: Mapping[str, float]) -> float:
    """Compute Hellinger fidelity: ``(sum_x sqrt(p(x) * q(x)))^2``."""
    keys = set(p) | set(q)
    bc = sum(math.sqrt(max(p.get(k, 0.0), 0.0) * max(q.get(k, 0.0), 0.0)) for k in keys)
    return min(1.0, bc * bc)


def compute_kl_divergence(
    p: Mapping[str, float], q: Mapping[str, float], epsilon: float = 1e-12
) -> float:
    """Compute smoothed KL divergence ``D_KL(p || q)``."""
    keys = set(p) | set(q)
    kl = 0.0
    for k in keys:
        pk = p.get(k, 0.0)
        if pk > 0.0:
            qk = max(q.get(k, 0.0), epsilon)
            kl += pk * math.log(pk / qk)
    return max(0.0, kl)


def compute_fidelity_metrics(
    reference_counts: Mapping[str, int | float],
    target_counts: Mapping[str, int | float],
) -> FidelityMetrics:
    """Compare two counts/probability distributions using TVD, Hellinger, and KL."""
    p = counts_to_probabilities(reference_counts)
    q = counts_to_probabilities(target_counts)
    return FidelityMetrics(
        total_variation_distance=compute_tvd(p, q),
        hellinger_fidelity=compute_hellinger_fidelity(p, q),
        kl_divergence=compute_kl_divergence(p, q),
    )


def _count_non_barrier_gates(circuit: QuantumCircuit) -> tuple[int, int]:
    """Return ``(total_gates, two_qubit_gates)`` excluding barriers and measurements."""
    total = 0
    two_q = 0
    for inst in circuit.data:
        name = inst.operation.name
        if name in {"barrier", "measure", "reset"}:
            continue
        total += 1
        if len(inst.qubits) >= 2:
            two_q += 1
    return total, two_q


def _pct_increase(orig: int, obf: int) -> float:
    if orig == 0:
        return 0.0 if obf == 0 else 100.0
    return ((obf - orig) / orig) * 100.0


def compute_circuit_overhead(
    original: QuantumCircuit,
    obfuscated: QuantumCircuit,
    cutting_sampling_overhead: float | None = None,
) -> CircuitOverheadMetrics:
    """Compute exact depth, total gate, and 2-qubit gate overhead."""
    orig_depth = int(original.depth())
    obf_depth = int(obfuscated.depth())
    orig_gates, orig_2q = _count_non_barrier_gates(original)
    obf_gates, obf_2q = _count_non_barrier_gates(obfuscated)

    return CircuitOverheadMetrics(
        original_depth=orig_depth,
        obfuscated_depth=obf_depth,
        depth_increase_abs=obf_depth - orig_depth,
        depth_increase_pct=round(_pct_increase(orig_depth, obf_depth), 2),
        original_gate_count=orig_gates,
        obfuscated_gate_count=obf_gates,
        gate_increase_abs=obf_gates - orig_gates,
        gate_increase_pct=round(_pct_increase(orig_gates, obf_gates), 2),
        original_two_qubit_gates=orig_2q,
        obfuscated_two_qubit_gates=obf_2q,
        two_qubit_increase_abs=obf_2q - orig_2q,
        two_qubit_increase_pct=round(_pct_increase(orig_2q, obf_2q), 2),
        cutting_sampling_overhead=cutting_sampling_overhead,
    )


def evaluate_privacy_metrics(
    original: QuantumCircuit,
    obfuscated: QuantumCircuit,
    key_bundle: ObfuscationKeyBundle,
    shots: int = 4096,
    depolarizing_1q: float = 0.001,
    depolarizing_2q: float = 0.01,
    readout_error: float = 0.015,
    cutting_sampling_overhead: float | None = None,
    seed: int = 42,
) -> PrivacyMetricsReport:
    """Evaluate structural overhead plus ideal & noisy Aer fidelity degradation."""
    overhead = compute_circuit_overhead(
        original,
        obfuscated,
        cutting_sampling_overhead=cutting_sampling_overhead,
    )

    if original.num_clbits == 0:
        return PrivacyMetricsReport(overhead=overhead)

    ideal_sim = AerSimulator()
    orig_compiled = transpile(original, ideal_sim, optimization_level=0)
    obf_compiled = transpile(obfuscated, ideal_sim, optimization_level=0)

    orig_ideal_counts = ideal_sim.run(
        orig_compiled, shots=shots, seed_simulator=seed
    ).result().get_counts()
    obf_ideal_raw = ideal_sim.run(
        obf_compiled, shots=shots, seed_simulator=seed + 1
    ).result().get_counts()
    obf_ideal_decoded = ObfuscationPipeline.decode_counts(obf_ideal_raw, key_bundle)

    noise_model = build_realistic_noise_model(
        depolarizing_1q=depolarizing_1q,
        depolarizing_2q=depolarizing_2q,
        readout_error=readout_error,
    )
    noisy_sim = AerSimulator(noise_model=noise_model)
    obf_noisy_compiled = transpile(obfuscated, noisy_sim, optimization_level=0)
    obf_noisy_raw = noisy_sim.run(
        obf_noisy_compiled, shots=shots, seed_simulator=seed + 2
    ).result().get_counts()
    obf_noisy_decoded = ObfuscationPipeline.decode_counts(obf_noisy_raw, key_bundle)

    return PrivacyMetricsReport(
        overhead=overhead,
        ideal_fidelity=compute_fidelity_metrics(orig_ideal_counts, obf_ideal_decoded),
        noisy_fidelity=compute_fidelity_metrics(orig_ideal_counts, obf_noisy_decoded),
    )
