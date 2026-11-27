"""Real circuit cutting & local classical reconstruction using qiskit-addon-cutting."""

from __future__ import annotations

import asyncio
from collections.abc import Hashable, Sequence
from dataclasses import dataclass

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit import Barrier, Measure
from qiskit.primitives import BitArray, DataBin, PrimitiveResult, SamplerPubResult
from qiskit.quantum_info import PauliList
from qiskit_addon_cutting import (
    DeviceConstraints,
    OptimizationParameters,
    cut_wires,
    find_cuts,
    generate_cutting_experiments,
    partition_problem,
    reconstruct_expectation_values,
)

from qcloak_proxy.backends.base import QuantumBackendAdapter
from qcloak_proxy.config import PrivacyProfile
from qcloak_proxy.obfuscation.pipeline import ObfuscationKeyBundle, ObfuscationPipeline


@dataclass
class CuttingMetadata:
    """Metadata describing a circuit-cutting decomposition."""

    num_partitions: int
    num_subexperiments: int
    sampling_overhead: float
    subcircuit_qubits: dict[str, int]
    cut_info: dict[str, object]


@dataclass
class CuttingExecutionResult:
    """Result of executing a cut circuit across backend(s) and reconstructing locally."""

    expectation_values: list[float]
    probabilities: dict[str, float]
    counts: dict[str, int]
    metadata: CuttingMetadata


def _strip_measurements(circuit: QuantumCircuit) -> QuantumCircuit:
    """Return a copy of ``circuit`` without Measure or final Barrier instructions."""
    clean = QuantumCircuit(*circuit.qregs)
    clean.global_phase = circuit.global_phase
    q_map = {old_q: new_q for old_q, new_q in zip(circuit.qubits, clean.qubits, strict=True)}
    for inst in circuit.data:
        if isinstance(inst.operation, Measure):
            continue
        if isinstance(inst.operation, Barrier):
            continue
        clean.append(inst.operation, [q_map[q] for q in inst.qubits])
    return clean


def _split_counts_by_creg(
    counts: dict[str, int], circuit: QuantumCircuit
) -> dict[str, BitArray]:
    """Split Qiskit space-separated or flat bitstring counts into per-register BitArrays."""
    cregs = list(circuit.cregs)
    if not cregs:
        return {}

    if len(cregs) == 1:
        reg = cregs[0]
        flat_counts = {k.replace(" ", ""): v for k, v in counts.items()}
        return {reg.name: BitArray.from_counts(flat_counts, num_bits=len(reg))}

    # Multiple cregs: Qiskit formats bitstrings as "<creg[-1]> ... <creg[0]>".
    # Expand aligned per-shot samples so shot i in each register corresponds to the same shot.
    per_reg_samples: list[list[str]] = [[] for _ in cregs]
    for raw_bits, count in counts.items():
        if count <= 0:
            continue
        flat = raw_bits.replace(" ", "")
        offset = 0
        for rev_idx, reg in enumerate(reversed(cregs)):
            orig_idx = len(cregs) - 1 - rev_idx
            seg = flat[offset : offset + len(reg)]
            offset += len(reg)
            per_reg_samples[orig_idx].extend([seg] * count)

    return {
        reg.name: BitArray.from_samples(per_reg_samples[i], num_bits=len(reg))
        for i, reg in enumerate(cregs)
    }


def _project_to_simplex(probs: np.ndarray) -> np.ndarray:
    """Project a quasi-probability vector onto the probability simplex (sum=1, p>=0)."""
    if len(probs) == 0:
        return probs
    u = np.sort(probs)[::-1]
    cssv = np.cumsum(u) - 1.0
    ind = np.arange(1, len(probs) + 1)
    cond = u - cssv / ind > 0
    rho = int(ind[cond][-1]) if np.any(cond) else 1
    theta = float(cssv[cond][-1] / rho) if np.any(cond) else 0.0
    projected = np.maximum(probs - theta, 0.0)
    total = float(projected.sum())
    return projected / total if total > 0.0 else np.full_like(probs, 1.0 / len(probs))


class CircuitCutter:
    """Partitions circuits via qiskit-addon-cutting, dispatches subexperiments,
    and reconstructs results classically on the local machine.
    """

    def __init__(
        self,
        max_subcircuit_qubits: int = 3,
        num_samples: int = 200,
        shots_per_subexperiment: int = 1024,
        privacy_profile: PrivacyProfile | None = PrivacyProfile.LOW,
        seed: int | None = None,
    ) -> None:
        self.max_subcircuit_qubits = max_subcircuit_qubits
        self.num_samples = num_samples
        self.shots_per_subexperiment = shots_per_subexperiment
        self.privacy_profile = privacy_profile
        self.seed = seed

    async def _execute_subexperiment(
        self,
        subcircuit: QuantumCircuit,
        backend: QuantumBackendAdapter,
        shots: int,
    ) -> SamplerPubResult:
        """Optionally cloak a subcircuit, run on backend, unmap counts, and wrap as PubResult."""
        key_bundle: ObfuscationKeyBundle | None = None
        to_run = subcircuit

        if self.privacy_profile is not None:
            pipeline = ObfuscationPipeline(profile=self.privacy_profile, seed=self.seed)
            to_run, key_bundle = pipeline.obfuscate(subcircuit)

        job_id = await backend.submit(to_run, shots=shots)
        raw_counts = await backend.result(job_id)

        if key_bundle is not None:
            decoded = ObfuscationPipeline.decode_counts(raw_counts, key_bundle)
            final_counts = {k: int(v) for k, v in decoded.items()}
        else:
            final_counts = raw_counts

        bitarrays = _split_counts_by_creg(final_counts, subcircuit)
        return SamplerPubResult(DataBin(**bitarrays))

    async def cut_and_evaluate(
        self,
        circuit: QuantumCircuit,
        observables: PauliList,
        backends: Sequence[QuantumBackendAdapter],
    ) -> tuple[list[float], CuttingMetadata]:
        """Cut ``circuit``, dispatch subexperiments across ``backends``, and reconstruct."""
        if not backends:
            raise ValueError("At least one QuantumBackendAdapter is required.")

        unitary_circuit = _strip_measurements(circuit)
        n_qubits = unitary_circuit.num_qubits
        if n_qubits == 0:
            raise ValueError("Cannot cut a 0-qubit circuit.")

        max_q = min(self.max_subcircuit_qubits, n_qubits)
        opt_params = OptimizationParameters(seed=self.seed)
        constraints = DeviceConstraints(qubits_per_subcircuit=max_q)

        cut_circuit, cut_info = find_cuts(unitary_circuit, opt_params, constraints)
        wire_cut_circuit = cut_wires(cut_circuit)
        partitioned = partition_problem(wire_cut_circuit, observables=observables)

        subexperiments, coefficients = generate_cutting_experiments(
            circuits=partitioned.subcircuits,
            observables=partitioned.subobservables,
            num_samples=self.num_samples,
        )

        # Dispatch all subexperiments across the provided backends concurrently
        tasks: list[tuple[Hashable, int, asyncio.Task[SamplerPubResult]]] = []
        backend_idx = 0

        if isinstance(subexperiments, dict):
            for label, circ_list in subexperiments.items():
                for idx, subcirc in enumerate(circ_list):
                    backend = backends[backend_idx % len(backends)]
                    backend_idx += 1
                    task = asyncio.create_task(
                        self._execute_subexperiment(
                            subcirc, backend, self.shots_per_subexperiment
                        )
                    )
                    tasks.append((label, idx, task))

            await asyncio.gather(*(t for _, _, t in tasks))

            grouped: dict[Hashable, list[SamplerPubResult]] = {
                label: [] for label in subexperiments
            }
            for label, _idx, task in tasks:
                grouped[label].append(task.result())

            results_arg: PrimitiveResult | dict[Hashable, PrimitiveResult] = {
                label: PrimitiveResult(pubs) for label, pubs in grouped.items()
            }
            subcircuit_qubits = {
                str(label): sc.num_qubits for label, sc in partitioned.subcircuits.items()
            }
            num_subexps = sum(len(v) for v in subexperiments.values())
        else:
            single_tasks = [
                asyncio.create_task(
                    self._execute_subexperiment(
                        subcirc,
                        backends[i % len(backends)],
                        self.shots_per_subexperiment,
                    )
                )
                for i, subcirc in enumerate(subexperiments)
            ]
            pubs = await asyncio.gather(*single_tasks)
            results_arg = PrimitiveResult(list(pubs))
            subcircuit_qubits = {"A": unitary_circuit.num_qubits}
            num_subexps = len(subexperiments)

        expvals = reconstruct_expectation_values(
            results_arg,
            coefficients,
            partitioned.subobservables,
        )

        sampling_overhead = float(cut_info.get("sampling_overhead", 1.0))
        metadata = CuttingMetadata(
            num_partitions=len(subcircuit_qubits),
            num_subexperiments=num_subexps,
            sampling_overhead=sampling_overhead,
            subcircuit_qubits=subcircuit_qubits,
            cut_info={str(k): v for k, v in cut_info.items()},
        )
        return [float(v) for v in expvals], metadata

    async def cut_and_reconstruct_distribution(
        self,
        circuit: QuantumCircuit,
        backends: Sequence[QuantumBackendAdapter],
        total_shots: int = 4096,
    ) -> CuttingExecutionResult:
        """Reconstruct the full Z-basis bitstring probability distribution via Walsh-Hadamard.

        Computes all ``2^n`` Z-basis Pauli expectation values using circuit cutting
        and transforms them into normalized bitstring probabilities and integer counts.
        """
        n_qubits = circuit.num_qubits
        if n_qubits > 6:
            raise ValueError(
                "Full distribution reconstruction via Walsh-Hadamard is intended for <= 6 qubits; "
                "use cut_and_evaluate with explicit PauliList observables for larger circuits."
            )

        # Build all 2^n Z-basis Pauli strings (Qiskit order: q[n-1]...q[0])
        pauli_strs: list[str] = []
        for mask in range(1 << n_qubits):
            chars = ["Z" if (mask >> q) & 1 else "I" for q in range(n_qubits - 1, -1, -1)]
            pauli_strs.append("".join(chars))

        observables = PauliList(pauli_strs)
        expvals, metadata = await self.cut_and_evaluate(circuit, observables, backends)

        # Walsh-Hadamard transform: P(x) = (1 / 2^n) * sum_S (-1)^(x . S) <Z^S>
        dim = 1 << n_qubits
        raw_probs = np.zeros(dim, dtype=np.float64)
        exp_arr = np.asarray(expvals, dtype=np.float64)
        for x in range(dim):
            signs = np.array(
                [1.0 if ((x & mask).bit_count() % 2 == 0) else -1.0 for mask in range(dim)],
                dtype=np.float64,
            )
            raw_probs[x] = float(np.dot(signs, exp_arr)) / float(dim)

        probs_arr = _project_to_simplex(raw_probs)

        probabilities: dict[str, float] = {}
        counts: dict[str, int] = {}
        for x in range(dim):
            bitstr = format(x, f"0{n_qubits}b")
            p = float(probs_arr[x])
            if p > 1e-6:
                probabilities[bitstr] = p
            c = round(p * total_shots)
            if c > 0:
                counts[bitstr] = c

        return CuttingExecutionResult(
            expectation_values=expvals,
            probabilities=probabilities,
            counts=counts,
            metadata=metadata,
        )
