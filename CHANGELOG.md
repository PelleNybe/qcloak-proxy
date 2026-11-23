# Changelog

All notable changes to `qcloak-proxy` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-23

### Added
- **Obfuscation Engine (`qcloak_proxy.obfuscation`)**:
  - `QubitPermutationPass` using CSPRNG (`secrets.randbelow`) for qubit and classical-bit rewiring plus exact multi-register bitstring unmapping.
  - `DummyGatesPass` inserting mathematically neutralizing single-qubit Euler ($U \cdot U^\dagger = I$) and conjugated two-qubit ($\text{CX}$ / $\text{CZ}$) blocks with configurable barrier fencing.
  - `ObfuscationPipeline` with `low`, `medium`, and `high` privacy profiles.
  - `CircuitCutter` integrating `qiskit-addon-cutting` for automatic cut discovery, multi-backend subexperiment dispatch, and local quasi-probability reconstruction.
- **Backend Adapters (`qcloak_proxy.backends`)**:
  - `LocalAerBackend` (noiseless & realistic depolarizing/readout `NoiseModel`).
  - `CloudQuantumClient` (`httpx` HTTP/2 + TLS + retries) supporting IBM Quantum Runtime and generic OpenQASM 3 runners.
- **FastAPI Proxy & SQLite WAL Store (`qcloak_proxy.server`)**:
  - `/submit`, `/status/{job_id}`, `/result/{job_id}`, `/metrics/{job_id}`, `/obfuscate`, `/jobs`, `DELETE /jobs/{job_id}`, `/health`.
  - Local SQLite WAL persistence with optional Fernet (`QCLOAK_STATE_ENCRYPTION_KEY`) encryption at rest keeping all decoding keys strictly on-premise.
- **Qiskit Plugin & CLI (`qcloak_proxy.provider`, `qcloak_proxy.cli`)**:
  - `QCloakProvider` (with context manager), `QCloakBackend` (`BackendV2`), and `QCloakJob` (`JobV1` + `.metrics()`) 1-line drop-in plugin.
  - `qcloak-proxy` Typer CLI (`serve`, `jobs`, `cloak`, `purge`, `benchmark`).
- **Metrics (`qcloak_proxy.metrics`)**:
  - Depth, gate, and 2-qubit gate overhead analysis plus ideal & noisy Aer TVD, Hellinger fidelity, and KL divergence.
