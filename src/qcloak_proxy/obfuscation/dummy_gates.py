"""Neutralizing dummy-gate insertion pass (U * U^dagger = I) for circuit obfuscation."""

from __future__ import annotations

import math
import secrets

import numpy as np
from qiskit.circuit import Barrier, Measure, Qubit, Reset
from qiskit.circuit.library import CXGate, CZGate, RXGate, RZGate, UGate
from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler.basepasses import TransformationPass


class DummyGatesPass(TransformationPass):
    """Insert mathematically neutralizing gate sequences (``U @ U^dagger == I``).

    This obscures circuit depth, gate density, and structural motifs while
    preserving the exact logical unitary operator.
    """

    def __init__(
        self,
        single_qubit_density: float = 0.25,
        two_qubit_density: float = 0.0,
        insert_barriers: bool = True,
        seed: int | None = None,
    ) -> None:
        super().__init__()
        if not 0.0 <= single_qubit_density <= 1.0:
            raise ValueError(
                f"single_qubit_density must be in [0.0, 1.0], got {single_qubit_density}"
            )
        if not 0.0 <= two_qubit_density <= 1.0:
            raise ValueError(
                f"two_qubit_density must be in [0.0, 1.0], got {two_qubit_density}"
            )
        self.single_qubit_density = single_qubit_density
        self.two_qubit_density = two_qubit_density
        self.insert_barriers = insert_barriers
        self.seed = seed

    def _make_rng(self) -> np.random.Generator:
        entropy = self.seed if self.seed is not None else secrets.randbits(128)
        return np.random.default_rng(entropy)

    def _emit_1q_neutral_block(
        self, dag: DAGCircuit, qubit: Qubit, rng: np.random.Generator
    ) -> None:
        theta, phi, lam = rng.uniform(0.0, 2.0 * math.pi, size=3)
        u_gate = UGate(float(theta), float(phi), float(lam))
        u_inv = u_gate.inverse()

        dag.apply_operation_back(u_gate, qargs=[qubit])
        if self.insert_barriers:
            dag.apply_operation_back(Barrier(1), qargs=[qubit])
        dag.apply_operation_back(u_inv, qargs=[qubit])

    def _emit_2q_neutral_block(
        self, dag: DAGCircuit, qa: Qubit, qb: Qubit, rng: np.random.Generator
    ) -> None:
        theta_a, phi_a, lam_a = rng.uniform(0.0, 2.0 * math.pi, size=3)
        u_a = UGate(float(theta_a), float(phi_a), float(lam_a))
        u_a_inv = u_a.inverse()

        if bool(rng.integers(0, 2)):
            # Conjugated CX block:
            # (U_a x U_b) CX (Rz(a) x Rx(b)) (Rz(-a) x Rx(-b)) CX (U_a^dag x U_b^dag) = I
            theta_b, phi_b, lam_b = rng.uniform(0.0, 2.0 * math.pi, size=3)
            u_b = UGate(float(theta_b), float(phi_b), float(lam_b))
            u_b_inv = u_b.inverse()
            alpha, beta = rng.uniform(0.0, 2.0 * math.pi, size=2)

            dag.apply_operation_back(u_a, qargs=[qa])
            dag.apply_operation_back(u_b, qargs=[qb])
            dag.apply_operation_back(CXGate(), qargs=[qa, qb])
            dag.apply_operation_back(RZGate(float(alpha)), qargs=[qa])
            dag.apply_operation_back(RXGate(float(beta)), qargs=[qb])
            if self.insert_barriers:
                dag.apply_operation_back(Barrier(2), qargs=[qa, qb])
            dag.apply_operation_back(RZGate(float(-alpha)), qargs=[qa])
            dag.apply_operation_back(RXGate(float(-beta)), qargs=[qb])
            dag.apply_operation_back(CXGate(), qargs=[qa, qb])
            dag.apply_operation_back(u_a_inv, qargs=[qa])
            dag.apply_operation_back(u_b_inv, qargs=[qb])
        else:
            # Conjugated CZ block: U_a CZ [Barrier] CZ U_a^dag = I
            dag.apply_operation_back(u_a, qargs=[qa])
            dag.apply_operation_back(CZGate(), qargs=[qa, qb])
            if self.insert_barriers:
                dag.apply_operation_back(Barrier(2), qargs=[qa, qb])
            dag.apply_operation_back(CZGate(), qargs=[qa, qb])
            dag.apply_operation_back(u_a_inv, qargs=[qa])

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Insert neutralizing single- and two-qubit blocks into the DAGCircuit."""
        rng = self._make_rng()

        new_dag = DAGCircuit()
        for qreg in dag.qregs.values():
            new_dag.add_qreg(qreg)
        extra_qubits = [q for q in dag.qubits if q not in set(new_dag.qubits)]
        if extra_qubits:
            new_dag.add_qubits(extra_qubits)
        for creg in dag.cregs.values():
            new_dag.add_creg(creg)
        extra_clbits = [c for c in dag.clbits if c not in set(new_dag.clbits)]
        if extra_clbits:
            new_dag.add_clbits(extra_clbits)
        new_dag.global_phase = dag.global_phase

        old_qubits = list(dag.qubits)
        new_qubits = list(new_dag.qubits)
        qubit_map = {old_qubits[i]: new_qubits[i] for i in range(len(old_qubits))}

        old_clbits = list(dag.clbits)
        new_clbits = list(new_dag.clbits)
        clbit_map = {old_clbits[j]: new_clbits[j] for j in range(len(old_clbits))}

        n_qubits = len(new_qubits)
        blocks_inserted = 0

        for node in dag.topological_op_nodes():
            mapped_qargs = [qubit_map[q] for q in node.qargs]
            mapped_cargs = [clbit_map[c] for c in node.cargs]

            is_barrier_or_reset = isinstance(node.op, (Barrier, Reset))
            is_measure = isinstance(node.op, Measure)

            if not is_barrier_or_reset and mapped_qargs:
                if not is_measure and self.single_qubit_density > 0.0:
                    for q in mapped_qargs:
                        if float(rng.random()) < self.single_qubit_density:
                            self._emit_1q_neutral_block(new_dag, q, rng)
                            blocks_inserted += 1
                elif is_measure and blocks_inserted == 0 and self.single_qubit_density > 0.0:
                    # Ensure small circuits with measurements still receive at least one block
                    self._emit_1q_neutral_block(new_dag, mapped_qargs[0], rng)
                    blocks_inserted += 1

                if (
                    not is_measure
                    and n_qubits >= 2
                    and self.two_qubit_density > 0.0
                    and float(rng.random()) < self.two_qubit_density
                ):
                    idx_a, idx_b = rng.choice(n_qubits, size=2, replace=False)
                    self._emit_2q_neutral_block(
                        new_dag, new_qubits[int(idx_a)], new_qubits[int(idx_b)], rng
                    )
                    blocks_inserted += 1

            new_dag.apply_operation_back(node.op, qargs=mapped_qargs, cargs=mapped_cargs)

        # Guarantee at least one neutralizing block if density > 0 and circuit had qubits
        if blocks_inserted == 0 and n_qubits > 0 and self.single_qubit_density > 0.0:
            # Insert at the beginning of a non-measured or first qubit before operations
            # Since we already copied all ops, we can't safely append after Measure,
            # so we only do this if there are no measurements at all.
            has_measure = any(isinstance(n.op, Measure) for n in dag.topological_op_nodes())
            if not has_measure:
                self._emit_1q_neutral_block(new_dag, new_qubits[0], rng)

        self.property_set["qcloak_dummy_blocks_inserted"] = blocks_inserted
        return new_dag
