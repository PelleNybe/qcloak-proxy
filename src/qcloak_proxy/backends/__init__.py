"""Quantum backend adapters for local simulation and remote cloud execution."""

from qcloak_proxy.backends.base import BackendInfo, BackendJobStatus, QuantumBackendAdapter
from qcloak_proxy.backends.cloud_client import CloudQuantumClient
from qcloak_proxy.backends.local_aer import LocalAerBackend, build_realistic_noise_model

__all__ = [
    "BackendInfo",
    "BackendJobStatus",
    "CloudQuantumClient",
    "LocalAerBackend",
    "QuantumBackendAdapter",
    "build_realistic_noise_model",
]
