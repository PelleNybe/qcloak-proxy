"""Composable obfuscation PassManager pipeline and decoding key bundle."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, Field
from qiskit import QuantumCircuit
from qiskit.transpiler import PassManager

from qcloak_proxy.config import PrivacyProfile
from qcloak_proxy.obfuscation.dummy_gates import DummyGatesPass
from qcloak_proxy.obfuscation.permutation import QubitPermutationPass, unmap_counts


@dataclass(frozen=True)
class ProfileParameters:
    """Parameters governing a privacy profile's obfuscation passes."""

    single_qubit_density: float
    two_qubit_density: float
    insert_barriers: bool


PROFILE_DEFAULTS: dict[PrivacyProfile, ProfileParameters] = {
    PrivacyProfile.LOW: ProfileParameters(
        single_qubit_density=0.0,
        two_qubit_density=0.0,
        insert_barriers=False,
    ),
    PrivacyProfile.MEDIUM: ProfileParameters(
        single_qubit_density=0.25,
        two_qubit_density=0.0,
        insert_barriers=True,
    ),
    PrivacyProfile.HIGH: ProfileParameters(
        single_qubit_density=0.50,
        two_qubit_density=0.20,
        insert_barriers=True,
    ),
}


class ObfuscationKeyBundle(BaseModel):
    """Serializable local decoding keys produced by the obfuscation pipeline.

    This bundle MUST remain strictly on the user's local machine.
    """

    privacy_profile: PrivacyProfile
    qubit_permutation: list[int] = Field(default_factory=list)
    clbit_permutation: list[int] = Field(default_factory=list)
    creg_sizes: list[int] = Field(default_factory=list)
    num_qubits: int
    num_clbits: int
    dummy_blocks_inserted: int = 0


class ObfuscationPipeline:
    """Builds and executes a Qiskit PassManager for reversible circuit cloaking."""

    def __init__(
        self,
        profile: PrivacyProfile = PrivacyProfile.MEDIUM,
        single_qubit_density: float | None = None,
        two_qubit_density: float | None = None,
        insert_barriers: bool | None = None,
        seed: int | None = None,
    ) -> None:
        self.profile = profile
        defaults = PROFILE_DEFAULTS[profile]
        self.single_qubit_density = (
            defaults.single_qubit_density
            if single_qubit_density is None
            else single_qubit_density
        )
        self.two_qubit_density = (
            defaults.two_qubit_density if two_qubit_density is None else two_qubit_density
        )
        self.insert_barriers = (
            defaults.insert_barriers if insert_barriers is None else insert_barriers
        )
        self.seed = seed

    def obfuscate(
        self,
        circuit: QuantumCircuit,
        qubit_permutation: list[int] | None = None,
        clbit_permutation: list[int] | None = None,
    ) -> tuple[QuantumCircuit, ObfuscationKeyBundle]:
        """Obfuscate ``circuit`` and return ``(cloaked_circuit, key_bundle)``."""
        perm_pass = QubitPermutationPass(
            qubit_permutation=qubit_permutation,
            clbit_permutation=clbit_permutation,
        )
        passes: list[QubitPermutationPass | DummyGatesPass] = [perm_pass]

        dummy_pass: DummyGatesPass | None = None
        if self.single_qubit_density > 0.0 or self.two_qubit_density > 0.0:
            dummy_pass = DummyGatesPass(
                single_qubit_density=self.single_qubit_density,
                two_qubit_density=self.two_qubit_density,
                insert_barriers=self.insert_barriers,
                seed=self.seed,
            )
            passes.append(dummy_pass)

        pm = PassManager(passes)
        cloaked = pm.run(circuit)

        q_perm = list(pm.property_set.get("qcloak_qubit_permutation", []))
        c_perm = list(pm.property_set.get("qcloak_clbit_permutation", []))
        dummy_count = int(pm.property_set.get("qcloak_dummy_blocks_inserted", 0))

        key_bundle = ObfuscationKeyBundle(
            privacy_profile=self.profile,
            qubit_permutation=q_perm,
            clbit_permutation=c_perm,
            creg_sizes=[len(creg) for creg in circuit.cregs],
            num_qubits=circuit.num_qubits,
            num_clbits=circuit.num_clbits,
            dummy_blocks_inserted=dummy_count,
        )
        return cloaked, key_bundle

    @staticmethod
    def decode_counts(
        counts: Mapping[str, int | float],
        key_bundle: ObfuscationKeyBundle,
    ) -> dict[str, int | float]:
        """Decode raw backend counts using the local ``ObfuscationKeyBundle``."""
        return unmap_counts(
            counts,
            clbit_permutation=key_bundle.clbit_permutation,
            creg_sizes=key_bundle.creg_sizes,
        )
