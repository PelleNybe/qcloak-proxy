# `qcloak-proxy` — Architecture & Implementation Plan

**Organization:** Corax CoLAB  
**Lead Developer:** Pelle Nyberg (`@PelleNybe`)  
**License:** Apache 2.0  

---

## 1. Executive Summary & Threat Model

`qcloak-proxy` is a local, zero-trust **Quantum Privacy Proxy** that sits between a user's quantum development environment (Qiskit or OpenQASM 3 clients) and untrusted third-party cloud quantum backends (QPUs and remote simulators). It protects proprietary quantum algorithms, circuit topologies, and intellectual property by transforming circuits locally before dispatch and reconstructing decoded results locally after execution.

**Core Security Invariant:** Unobfuscated circuits, permutation keys, classical bitstring unmapping tables, and circuit-cutting quasi-probability reconstruction coefficients **never leave the user's local machine**.

---

## 2. Mathematical Design of Reversible Obfuscation Passes

### 2.1 Cryptographically Secure Qubit & Classical Bit Permutation (`permutation.py`)

Given an $n$-qubit, $m$-clbit quantum circuit $C$ acting on Hilbert space $\mathcal{H} = (\mathbb{C}^2)^{\otimes n}$:

1. **Permutation Generation:** Using Python's `secrets.randbelow` (CSPRNG, Fisher-Yates shuffle), we sample:
   - A qubit permutation $\pi \in S_n$, mapping logical qubit $q_i \mapsto q_{\pi(i)}$.
   - A classical bit permutation $\sigma \in S_m$, mapping logical classical bit $c_j \mapsto c_{\sigma(j)}$ (so measurement correlations between qubit wire indices and classical register indices are also masked).
2. **Circuit Rewiring (`TransformationPass`):**
   - Construct a new `DAGCircuit` with the same quantum and classical register structure (or flat `q` and `c` registers of matching widths).
   - For every operation `op(q_{i_1}, ..., q_{i_k}; c_{j_1}, ..., c_{j_r})`, emit `op(q_{\pi(i_1)}, ..., q_{\pi(i_k)}; c_{\sigma(j_1)}, ..., c_{\sigma(j_r)})`.
   - Since $\pi$ and $\sigma$ are bijections, the unitary evolution $U_{\text{perm}} = P_\pi U P_\pi^\dagger$ is unitarily equivalent to $U$ up to wire relabeling.
3. **Deterministic Classical Bitstring Unmapping:**
   - Qiskit represents bitstring keys in `counts` dictionaries in big-endian bit order: $b = b_{m-1} b_{m-2} \dots b_0$, where character index `m - 1 - j` corresponds to classical bit `c[j]`.
   - When the remote backend returns counts over permuted classical bits $c_{\sigma(j)}$, the bit at logical index $j$ is located at physical classical index $\sigma(j)$ in the returned bitstring.
   - Therefore, for each returned bitstring $b'$, the unmapped bitstring $b$ has $b_j = b'_{\sigma(j)}$ for all $j \in \{0, \dots, m-1\}$.
   - Multi-register bitstrings (space-separated in Qiskit, e.g., `"01 101"`) are flattened via register offsets, unmapped bit-by-bit, and re-formatted with the exact original register spacing.

### 2.2 Neutralizing Gate Blocks ($U \cdot U^\dagger = I$) (`dummy_gates.py`)

To obscure circuit depth, gate density, and structural motifs without altering the logical unitary:

1. **Single-Qubit Neutralizing Blocks:**
   - Sample random Euler angles $(\theta, \phi, \lambda) \in [0, 2\pi)^3$ using `secrets` / `numpy.random.Generator` seeded from `secrets.randbits(128)`.
   - Insert $U(\theta, \phi, \lambda)$ followed by its exact adjoint $U^\dagger = U(-\theta, -\lambda, -\phi)$ (via Qiskit `UGate.inverse()`).
   - Mathematically: $U(\theta, \phi, \lambda) \cdot U(\theta, \phi, \lambda)^\dagger = I_2$.
2. **Two-Qubit Entangling Neutralizing Blocks:**
   - For adjacent or randomly selected qubit pairs $(q_a, q_b)$:
     - **CNOT / CZ Pairs:** $\text{CX}_{a,b} \cdot \text{CX}_{a,b} = I_4$ and $\text{CZ}_{a,b} \cdot \text{CZ}_{a,b} = I_4$.
     - **Conjugated Entangling Blocks:** $(U_a \otimes U_b) \cdot \text{CX}_{a,b} \cdot (R_z(\alpha)_a \otimes R_x(\beta)_b) \cdot (R_z(-\alpha)_a \otimes R_x(-\beta)_b) \cdot \text{CX}_{a,b} \cdot (U_a^\dagger \otimes U_b^\dagger) = I_4$.
3. **Barrier & Scheduling Considerations:**
   - Cloud transpilers performing peephole optimization (e.g., `Optimize1qGatesDecomposition`, `CXCancellation`) could cancel adjacent $U \cdot U^\dagger$ pairs if unguarded.
   - Configurable `insert_barriers: bool` places Qiskit `Barrier` instructions between $U$ and $U^\dagger$ (or around neutralizing blocks) in `medium` and `high` privacy profiles, forcing the remote compiler to preserve the obfuscating structure while keeping the overall unitary strictly equal to $I$.

### 2.3 Composable Pipeline & Privacy Profiles (`pipeline.py`)

Three standard profiles (plus custom overrides):
- **`low`**: Qubit & classical bit permutation only (zero gate/depth overhead, zero noise penalty).
- **`medium`**: Permutation + single-qubit neutralizing blocks (`density=0.25`) + barriers.
- **`high`**: Permutation + single- and two-qubit neutralizing blocks (`density=0.5`, `two_qubit_density=0.2`) + barriers.

Each pipeline execution returns `(obfuscated_circuit, ObfuscationKeyBundle)` where `ObfuscationKeyBundle` is JSON-serializable for encrypted/local SQLite persistence.

---

## 3. Circuit Cutting & Classical Reconstruction (`cutter.py`)

Using **`qiskit-addon-cutting`**:
1. **Cut Discovery & Partitioning:**
   - Automatically identify optimal wire/gate cuts using `find_cuts` with `OptimizationParameters` and `DeviceConstraints(qubits_per_subcircuit=max_qubits)`.
   - Partition the circuit into smaller subcircuits that fit smaller QPUs or hide the global entanglement graph across multiple independent backends.
2. **Subexperiment Generation:**
   - Use `generate_cutting_experiments` to produce quasi-probability subexperiments and sampling weights/coefficients.
   - Each subcircuit can optionally be further obfuscated via `pipeline.py` before dispatch.
3. **Multi-Job / Multi-Backend Dispatch:**
   - Dispatch subexperiments concurrently across one or more `QuantumBackendAdapter` instances via `asyncio.gather`.
4. **Local Classical Reconstruction:**
   - Reconstruct expectation values using `reconstruct_expectation_values` from `qiskit-addon-cutting` for Pauli observables, and reconstruct full bitstring probability distributions by combining subcircuit marginal counts weighted by the quasi-probability coefficients (with L1-simplex projection to ensure valid non-negative normalized probabilities).

---

## 4. FastAPI Proxy, SQLite State Store & Backend Adapters

### 4.1 Local SQLite State Store (`server/state_store.py`)
- SQLite in **WAL mode** (`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;`).
- Stores `jobs` table: `job_id`, `status`, `backend_name`, `privacy_profile`, `created_at`, `updated_at`, `original_qasm`, `obfuscated_qasm`, `key_bundle_json`, `cutting_metadata_json`, `backend_job_ids_json`, `raw_counts_json`, `decoded_counts_json`, `metrics_json`, `error_message`.
- All sensitive artifacts (`original_qasm`, `key_bundle_json`, `cutting_metadata_json`, `decoded_counts_json`) remain strictly on disk locally.

### 4.2 FastAPI Proxy (`server/api.py`)
- `GET /health`: Liveness, version, and registered backends.
- `POST /submit`: Accepts OpenQASM 3 (or QASM 2) circuit, `shots`, `privacy_profile`, `backend`, optional `enable_cutting` & `max_subcircuit_qubits`. Runs obfuscation/cutting locally, persists key bundle, dispatches cloaked circuit(s) asynchronously, returns `job_id`.
- `GET /status/{job_id}`: Polls/returns current job status (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`).
- `GET /result/{job_id}`: Retrieves raw counts from backend if needed, applies local unmapping / cutting reconstruction, caches decoded counts, and returns decoded probabilities & counts.
- `GET /metrics/{job_id}`: Returns exact "Price of Privacy" metrics (depth overhead, gate count overhead, 2-qubit gate overhead, cutting sampling overhead, TVD & Hellinger fidelity when reference or noise simulation is requested).

### 4.3 Backend Adapters (`backends/`)
- `base.py`: Abstract `QuantumBackendAdapter` (`submit`, `status`, `result`, `info`).
- `local_aer.py`: Real `qiskit-aer` `AerSimulator` supporting both noiseless statevector/shot simulation and configurable depolarizing + readout error `NoiseModel`.
- `cloud_client.py`: Production `httpx.AsyncClient` with HTTP/2, TLS verification, bearer/API-key auth headers, exponential backoff retries, and clean adapter support for IBM Quantum Runtime REST API (`/jobs`) and generic OpenQASM 3 HTTP runners.

---

## 5. Qiskit `BackendV2` & `QCloakProvider` Plugin (`provider/`)

- `QCloakProvider(proxy_url: str = "http://localhost:8000", api_key: str | None = None)`:
  - `backends()` / `get_backend(name)`: Discovers available backends from `/health` or instantiates `QCloakBackend`.
- `QCloakBackend(BackendV2)`:
  - Implements `target`, `max_circuits`, `_default_options`, and `run(run_input, **options)`.
  - Converts Qiskit `QuantumCircuit` (or list of circuits) to OpenQASM 3, submits to `qcloak-proxy`, and returns `QCloakJob(JobV1)`.
- `QCloakJob(JobV1)`:
  - Implements `submit()`, `status()`, `result()`, `cancel()`, returning a standard Qiskit `Result` object with decoded counts so existing Qiskit code works with a 1-line swap.

---

## 6. Milestones & Acceptance Criteria

| Phase | Milestone | Mathematical & Integration Acceptance Criteria |
| :--- | :--- | :--- |
| **Phase 1** | Obfuscation Engine (`permutation.py`, `dummy_gates.py`, `pipeline.py`) | Operator equivalence $U_{\text{obf}} \equiv P_\pi U P_\pi^\dagger$ verified via `Operator.equiv`; TVD $< 0.05$ and Hellinger fidelity $> 0.99$ on `qiskit-aer` across Bell, GHZ, QFT, and random circuits (including multi-register). |
| **Phase 2** | FastAPI Proxy, SQLite WAL Store & Cloud/Aer Backends | End-to-end `POST /submit` -> `GET /status` -> `GET /result` with OpenQASM 3 circuits; SQLite WAL persistence verified across restarts; `cloud_client.py` tested against mocked ASGI/HTTP2 transport for IBM Runtime & generic QASM3. |
| **Phase 3** | Circuit Cutting (`cutter.py`) & Metrics (`metrics.py`) | Real `qiskit-addon-cutting` partitioning + reconstruction on 4–6 qubit circuits; reconstructed expectation values & distributions match uncut `qiskit-aer` reference; `metrics.py` computes exact depth/gate/2Q overheads & noisy vs. noiseless TVD/Hellinger fidelity. |
| **Phase 4** | Qiskit `BackendV2` Plugin, CLI & Full Docs | 1-line `QCloakProvider` drop-in executes real circuits through FastAPI proxy returning standard Qiskit `Result`; `typer` CLI launches server & runs privacy benchmarks; `ruff`, `mypy`, `pytest` 100% green; complete docs & marketing `README.md`. |
