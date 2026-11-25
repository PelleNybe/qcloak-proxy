# User Manual — `qcloak-proxy`

## 1. Installation

```bash
pip install -e .
```
Or with `uv`:
```bash
uv pip install -e .
```

---

## 2. Launching the Local Proxy Server

```bash
qcloak-proxy serve --host 127.0.0.1 --port 8000 --privacy-profile medium
```

Once running, open `http://127.0.0.1:8000/` (or `/ui`) in your browser to access the embedded **Web Dashboard** (dry-run circuit cloaking auditor, decoded probability histograms, and SQLite key vault), or `http://127.0.0.1:8000/docs` for Swagger OpenAPI.

### Environment Variables (`QCLOAK_*`)
| Variable | Default | Description |
| :--- | :--- | :--- |
| `QCLOAK_PRIVACY_PROFILE` | `medium` | `low`, `medium`, or `high` |
| `QCLOAK_DB_PATH` | `qcloak_proxy.db` | Local SQLite WAL database path |
| `QCLOAK_DEFAULT_BACKEND` | `qcloak_aer` | Default backend name |
| `QCLOAK_PROXY_API_KEY` | `None` | Optional Bearer token for local API |
| `QCLOAK_STATE_ENCRYPTION_KEY` | `None` | Optional passphrase/Fernet key for encrypting SQLite keys at rest |
| `QCLOAK_CORS_ORIGINS` | `[]` | Allowed CORS origins (JSON list) |
| `QCLOAK_CLOUD_ENDPOINT` | `None` | Remote cloud API base URL |
| `QCLOAK_CLOUD_API_TOKEN` | `None` | Remote cloud API Bearer token |
| `QCLOAK_CLOUD_PROVIDER_TYPE` | `qasm3_runner` | `qasm3_runner` or `ibm_runtime` |

---

## 3. 1-Line Qiskit Drop-In Usage

```python
from qiskit import QuantumCircuit
from qcloak_proxy.provider import QCloakProvider

# 1-line drop-in replacement for any Qiskit BackendV2
backend = QCloakProvider("http://127.0.0.1:8000").get_backend("qcloak_aer")

qc = QuantumCircuit(3, 3)
qc.h(0)
qc.cx(0, 1)
qc.cx(1, 2)
qc.measure([0, 1, 2], [0, 1, 2])

result = backend.run(qc, shots=2048, privacy_profile="high").result()
print(result.get_counts())
```

---

## 4. Running Privacy & Noise Benchmarks

```bash
qcloak-proxy benchmark --qubits 4 --shots 4096
```

## 5. Inspecting, Cloaking & Purging via CLI

```bash
# Dry-run cloak an OpenQASM 3 file locally and inspect overhead
qcloak-proxy cloak circuit.qasm --profile high --output cloaked.qasm

# Inspect local job history
qcloak-proxy jobs --db-path qcloak_proxy.db --limit 20

# Purge a job and its local decoding keys
qcloak-proxy purge qcloak-a1b2c3d4e5f6 --db-path qcloak_proxy.db
```
