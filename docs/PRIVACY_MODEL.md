# Privacy & Threat Model — `qcloak-proxy`

## 1. Threat Model

`qcloak-proxy` assumes an **honest-but-curious** or **IP-harvesting** cloud quantum provider:
- The cloud provider **executes** the submitted circuit faithfully (up to hardware noise) and returns measurement counts.
- However, the cloud provider (or an intermediary inspecting cloud job queues) may attempt to **reverse-engineer** proprietary quantum algorithms, ansatz topologies, oracle structures, or problem instances from the submitted OpenQASM 3 circuits.

### What `qcloak-proxy` Protects
1. **Qubit & Classical Register Topology:** Random CSPRNG permutations ($\pi \in S_n, \sigma \in S_m$) hide which logical qubits interact and which classical bits correspond to which logical outputs.
2. **Circuit Depth & Gate Density:** Neutralizing $U \cdot U^\dagger = I$ blocks (single-qubit Euler rotations and conjugated $\text{CX}/\text{CZ}$ pairs) mask the true gate count, entangling density, and structural motifs.
3. **Global Circuit Structure (via Circuit Cutting):** `qiskit-addon-cutting` partitions a large circuit into smaller subcircuits that can be dispatched to **different** cloud providers/backends, ensuring no single provider ever sees the full algorithm.
4. **Local-Only Key Custody:** Permutation keys, `ObfuscationKeyBundle`, and cutting quasi-probability coefficients are stored exclusively in the local SQLite WAL database (`qcloak_proxy.db`).

---

## 2. Cryptographic & Mathematical Guarantees

- **CSPRNG Source:** All permutations use `secrets.randbelow` (OS CSPRNG), and dummy-gate angles use `numpy.random.default_rng(secrets.randbits(128))`.
- **Exact Unitary Preservation:**
  - Permutation: $U_{\text{perm}} = P_\pi U P_\pi^\dagger$.
  - Neutralizing 1Q block: $U(\theta,\phi,\lambda) \cdot U(\theta,\phi,\lambda)^\dagger = I_2$.
  - Neutralizing 2Q block: $(U_a \otimes U_b) \text{CX}_{a,b} (R_z(\alpha)_a \otimes R_x(\beta)_b) (R_z(-\alpha)_a \otimes R_x(-\beta)_b) \text{CX}_{a,b} (U_a^\dagger \otimes U_b^\dagger) = I_4$.

---

## 3. Privacy vs. Noise Trade-Off ("Price of Privacy")

| Profile | Permutation | 1Q Neutral Blocks | 2Q Neutral Blocks | Barriers | Noise Impact |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`low`** | Yes ($S_n \times S_m$) | `0.00` | `0.00` | No | **Zero** gate/noise overhead |
| **`medium`** | Yes ($S_n \times S_m$) | `0.25` | `0.00` | Yes | Low (1Q depolarizing only) |
| **`high`** | Yes ($S_n \times S_m$) | `0.50` | `0.20` | Yes | Moderate (2Q depolarizing + depth) |

Users should select `low` on noisy NISQ hardware when only wire/output obfuscation is needed, `medium` for balanced structural cloaking, and `high` (or circuit cutting) when maximum IP protection is required.
