"""Phase 1 verification tests: Obfuscation passes, unitary equivalence, and Aer fidelity."""

from __future__ import annotations

import math

import numpy as np
import pytest
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.circuit.library import QFTGate
from qiskit.quantum_info import Operator
from qiskit_aer import AerSimulator

from qcloak_proxy.config import PrivacyProfile
from qcloak_proxy.obfuscation import (
    DummyGatesPass,
    ObfuscationPipeline,
    QubitPermutationPass,
    invert_permutation,
    unmap_bitstring,
)


def _counts_to_probs(counts: dict[str, int | float]) -> dict[str, float]:
    total = float(sum(counts.values()))
    return {k: float(v) / total for k, v in counts.items()}


def _tvd(p: dict[str, float], q: dict[str, float]) -> float:
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys)


def _hellinger_fidelity(p: dict[str, float], q: dict[str, float]) -> float:
    keys = set(p) | set(q)
    bc = sum(math.sqrt(p.get(k, 0.0) * q.get(k, 0.0)) for k in keys)
    return bc * bc


def test_unmap_bitstring_single_and_multi_register() -> None:
    # Single register, 3 bits, permutation: logical [0,1,2] -> physical [2,0,1]
    # Logical c="101" -> physical c_phys[2]=1, c_phys[0]=0, c_phys[1]=1 -> "110"
    perm = [2, 0, 1]
    assert unmap_bitstring("110", perm) == "101"

    # Multi-register: c1 (2 bits), c2 (1 bit) -> creg_sizes=[2, 1]
    # Qiskit format: "c2 c1"
    # Logical "1 01" -> c[0]=1, c[1]=0, c[2]=1 -> physical "1 10"
    assert unmap_bitstring("1 10", perm, creg_sizes=[2, 1]) == "1 01"


def test_dummy_gates_unitary_equivalence() -> None:
    qc = QuantumCircuit(3)
    qc.h(0)
    qc.cx(0, 1)
    qc.rz(0.7, 1)
    qc.cx(1, 2)
    qc.rx(1.2, 2)

    orig_op = Operator(qc)

    dummy_pass = DummyGatesPass(
        single_qubit_density=1.0,
        two_qubit_density=1.0,
        insert_barriers=False,
        seed=42,
    )
    obf_qc = dummy_pass(qc)
    obf_op = Operator(obf_qc)
    assert orig_op.equiv(obf_op), "DummyGatesPass altered the circuit unitary!"


def test_permutation_pass_unitary_equivalence() -> None:
    qc = QuantumCircuit(3)
    qc.h(0)
    qc.cx(0, 1)
    qc.t(2)
    qc.cz(1, 2)

    perm_pass = QubitPermutationPass(qubit_permutation=[2, 0, 1], clbit_permutation=[])
    perm_qc = perm_pass(qc)

    # Unpermute back to original wire order to verify exact unitary equivalence
    inv = invert_permutation([2, 0, 1])
    unperm_pass = QubitPermutationPass(qubit_permutation=inv, clbit_permutation=[])
    restored_qc = unperm_pass(perm_qc)

    assert Operator(qc).equiv(Operator(restored_qc))


@pytest.mark.parametrize(
    "profile", [PrivacyProfile.LOW, PrivacyProfile.MEDIUM, PrivacyProfile.HIGH]
)
def test_bell_state_aer_fidelity(profile: PrivacyProfile) -> None:
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])

    sim = AerSimulator()
    shots = 4096
    orig_counts = sim.run(qc, shots=shots, seed_simulator=123).result().get_counts()

    pipeline = ObfuscationPipeline(profile=profile, seed=99)
    cloaked, key_bundle = pipeline.obfuscate(qc)
    raw_counts = sim.run(cloaked, shots=shots, seed_simulator=456).result().get_counts()
    decoded_counts = pipeline.decode_counts(raw_counts, key_bundle)

    p = _counts_to_probs(orig_counts)
    q = _counts_to_probs(decoded_counts)
    assert _tvd(p, q) < 0.04
    assert _hellinger_fidelity(p, q) > 0.995


@pytest.mark.parametrize(
    "profile", [PrivacyProfile.LOW, PrivacyProfile.MEDIUM, PrivacyProfile.HIGH]
)
def test_ghz_4q_aer_fidelity(profile: PrivacyProfile) -> None:
    qc = QuantumCircuit(4, 4)
    qc.h(0)
    for i in range(3):
        qc.cx(i, i + 1)
    qc.measure(range(4), range(4))

    sim = AerSimulator()
    shots = 4096
    orig_counts = sim.run(qc, shots=shots, seed_simulator=101).result().get_counts()

    pipeline = ObfuscationPipeline(profile=profile, seed=202)
    cloaked, key_bundle = pipeline.obfuscate(qc)
    raw_counts = sim.run(cloaked, shots=shots, seed_simulator=303).result().get_counts()
    decoded_counts = pipeline.decode_counts(raw_counts, key_bundle)

    p = _counts_to_probs(orig_counts)
    q = _counts_to_probs(decoded_counts)
    assert _tvd(p, q) < 0.04
    assert _hellinger_fidelity(p, q) > 0.995


def test_qft_4q_high_privacy_aer_fidelity() -> None:
    qc = QuantumCircuit(4, 4)
    qc.x(0)
    qc.x(2)
    qc.append(QFTGate(4), range(4))
    qc.measure(range(4), range(4))

    sim = AerSimulator()
    shots = 4096
    # Decompose QFTGate for Aer execution
    orig_decomposed = qc.decompose()
    orig_counts = sim.run(orig_decomposed, shots=shots, seed_simulator=11).result().get_counts()

    pipeline = ObfuscationPipeline(profile=PrivacyProfile.HIGH, seed=77)
    cloaked, key_bundle = pipeline.obfuscate(orig_decomposed)
    raw_counts = sim.run(cloaked, shots=shots, seed_simulator=22).result().get_counts()
    decoded_counts = pipeline.decode_counts(raw_counts, key_bundle)

    p = _counts_to_probs(orig_counts)
    q = _counts_to_probs(decoded_counts)
    assert _tvd(p, q) < 0.05
    assert _hellinger_fidelity(p, q) > 0.99


def test_random_circuit_multi_register_aer_fidelity() -> None:
    rng = np.random.default_rng(2026)
    qr = QuantumRegister(5, "q")
    cr1 = ClassicalRegister(2, "c1")
    cr2 = ClassicalRegister(3, "c2")
    qc = QuantumCircuit(qr, cr1, cr2)

    for _ in range(15):
        q = int(rng.integers(0, 5))
        theta, phi, lam = rng.uniform(0, 2 * math.pi, size=3)
        qc.u(float(theta), float(phi), float(lam), q)
        if rng.random() < 0.5:
            q2 = (q + int(rng.integers(1, 5))) % 5
            qc.cx(q, q2)

    qc.measure([0, 1], cr1)
    qc.measure([2, 3, 4], cr2)

    sim = AerSimulator()
    shots = 8192
    orig_counts = sim.run(qc, shots=shots, seed_simulator=1).result().get_counts()

    pipeline = ObfuscationPipeline(profile=PrivacyProfile.HIGH, seed=55)
    cloaked, key_bundle = pipeline.obfuscate(qc)
    raw_counts = sim.run(cloaked, shots=shots, seed_simulator=2).result().get_counts()
    decoded_counts = pipeline.decode_counts(raw_counts, key_bundle)

    p = _counts_to_probs(orig_counts)
    q = _counts_to_probs(decoded_counts)
    assert _tvd(p, q) < 0.05
    assert _hellinger_fidelity(p, q) > 0.99
