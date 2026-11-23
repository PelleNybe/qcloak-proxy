"""Cryptographically secure qubit & classical-bit permutation pass and bitstring unmapper."""

from __future__ import annotations

import secrets
from collections.abc import Mapping

from qiskit.dagcircuit import DAGCircuit
from qiskit.transpiler.basepasses import TransformationPass


def generate_secure_permutation(size: int) -> list[int]:
    """Generate a cryptographically secure random permutation of ``0..size-1``.

    Uses Fisher-Yates shuffle backed by ``secrets.randbelow``.
    """
    if size < 0:
        raise ValueError(f"Permutation size must be non-negative, got {size}")
    perm = list(range(size))
    for i in range(size - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        perm[i], perm[j] = perm[j], perm[i]
    return perm


def invert_permutation(perm: list[int]) -> list[int]:
    """Return the inverse permutation ``inv`` such that ``inv[perm[i]] == i``."""
    inv = [0] * len(perm)
    for i, p in enumerate(perm):
        inv[p] = i
    return inv


def unmap_bitstring(
    bitstring: str,
    clbit_permutation: list[int],
    creg_sizes: list[int] | None = None,
) -> str:
    """Restore a measured bitstring from permuted classical bits to logical order.

    Qiskit formats bitstrings in big-endian order (``c[m-1]...c[0]``), with
    multiple classical registers separated by spaces in reverse registration
    order.

    Args:
        bitstring: Raw bitstring returned by the backend.
        clbit_permutation: Mapping ``logical_clbit_idx -> physical_clbit_idx``.
        creg_sizes: Optional list of classical register widths in registration order.

    Returns:
        Unmapped bitstring in the original logical classical register order.
    """
    m = len(clbit_permutation)
    if m == 0:
        return bitstring

    flat = bitstring.replace(" ", "")
    if len(flat) != m:
        raise ValueError(
            f"Bitstring length {len(flat)} does not match clbit_permutation length {m}"
        )

    unmapped_chars = ["0"] * m
    for logical_idx, physical_idx in enumerate(clbit_permutation):
        unmapped_chars[m - 1 - logical_idx] = flat[m - 1 - physical_idx]

    unmapped_flat = "".join(unmapped_chars)

    if creg_sizes and len(creg_sizes) > 1:
        # Qiskit prints registers in reverse order of circuit.cregs
        parts: list[str] = []
        offset = 0
        for size in reversed(creg_sizes):
            parts.append(unmapped_flat[offset : offset + size])
            offset += size
        return " ".join(parts)

    return unmapped_flat


def unmap_counts(
    counts: Mapping[str, int | float],
    clbit_permutation: list[int],
    creg_sizes: list[int] | None = None,
) -> dict[str, int | float]:
    """Unmap all bitstrings in a counts or quasi-probability dictionary."""
    decoded: dict[str, int | float] = {}
    for raw_bits, value in counts.items():
        logical_bits = unmap_bitstring(raw_bits, clbit_permutation, creg_sizes=creg_sizes)
        decoded[logical_bits] = decoded.get(logical_bits, 0) + value
    return decoded


class QubitPermutationPass(TransformationPass):
    """Rewire all qubits and classical bits using a cryptographically secure permutation.

    The unitary operator is preserved up to wire relabeling:
    ``U_perm = P_pi @ U @ P_pi^dagger``.
    """

    def __init__(
        self,
        qubit_permutation: list[int] | None = None,
        clbit_permutation: list[int] | None = None,
    ) -> None:
        super().__init__()
        self.qubit_permutation = qubit_permutation
        self.clbit_permutation = clbit_permutation

    @staticmethod
    def _validate_permutation(perm: list[int], expected_len: int, label: str) -> None:
        if len(perm) != expected_len or sorted(perm) != list(range(expected_len)):
            raise ValueError(
                f"Invalid {label} permutation: expected a bijection of 0..{expected_len - 1}, "
                f"got {perm}"
            )

    def run(self, dag: DAGCircuit) -> DAGCircuit:
        """Apply qubit and classical-bit permutation to the DAGCircuit."""
        n_qubits = dag.num_qubits()
        n_clbits = dag.num_clbits()

        q_perm = (
            list(self.qubit_permutation)
            if self.qubit_permutation is not None
            else generate_secure_permutation(n_qubits)
        )
        c_perm = (
            list(self.clbit_permutation)
            if self.clbit_permutation is not None
            else generate_secure_permutation(n_clbits)
        )

        self._validate_permutation(q_perm, n_qubits, "qubit")
        self._validate_permutation(c_perm, n_clbits, "clbit")

        self.qubit_permutation = q_perm
        self.clbit_permutation = c_perm
        self.property_set["qcloak_qubit_permutation"] = q_perm
        self.property_set["qcloak_clbit_permutation"] = c_perm

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
        old_clbits = list(dag.clbits)
        new_clbits = list(new_dag.clbits)

        qubit_map = {old_qubits[i]: new_qubits[q_perm[i]] for i in range(n_qubits)}
        clbit_map = {old_clbits[j]: new_clbits[c_perm[j]] for j in range(n_clbits)}

        for node in dag.topological_op_nodes():
            mapped_qargs = [qubit_map[q] for q in node.qargs]
            mapped_cargs = [clbit_map[c] for c in node.cargs]
            new_dag.apply_operation_back(node.op, qargs=mapped_qargs, cargs=mapped_cargs)

        return new_dag
