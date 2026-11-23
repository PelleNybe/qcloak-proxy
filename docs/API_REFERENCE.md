# API Reference — `qcloak-proxy`

Base URL (default): `http://127.0.0.1:8000`  
Interactive OpenAPI / Swagger UI: `http://127.0.0.1:8000/docs`

If `QCLOAK_PROXY_API_KEY` is configured, all endpoints except `/health` require `Authorization: Bearer <token>`.

---

## `GET /health`
Returns server status, package version, and registered quantum backends.

**Response (`200 OK`):**
```json
{
  "status": "ok",
  "version": "0.1.0",
  "backends": [
    {
      "name": "qcloak_aer",
      "backend_type": "local_aer",
      "num_qubits": 28,
      "is_simulator": true,
      "has_noise_model": false
    }
  ]
}
```

---

## `POST /submit`
Submits an OpenQASM 3 (or OpenQASM 2) circuit for local cloaking (and optional circuit cutting) before dispatching to the target backend.

**Request Body:**
```json
{
  "qasm3": "OPENQASM 3.0;\ninclude \"stdgates.inc\";\nqubit[2] q;\nbit[2] c;\nh q[0];\ncx q[0], q[1];\nc = measure q;",
  "shots": 2048,
  "backend": "qcloak_aer",
  "privacy_profile": "medium",
  "enable_cutting": false,
  "max_subcircuit_qubits": 3
}
```

**Response (`202 Accepted`):**
```json
{
  "job_id": "qcloak-a1b2c3d4e5f6",
  "status": "COMPLETED",
  "backend": "qcloak_aer",
  "privacy_profile": "medium",
  "cutting_enabled": false
}
```

---

## `GET /status/{job_id}`
Polls the current status of a submitted job (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`).

---

## `GET /result/{job_id}`
Retrieves raw counts from the backend (if not yet cached), applies local bitstring unmapping / cutting reconstruction, and returns decoded counts and normalized probabilities.

**Response (`200 OK`):**
```json
{
  "job_id": "qcloak-a1b2c3d4e5f6",
  "status": "COMPLETED",
  "backend": "qcloak_aer",
  "shots": 2048,
  "counts": {"00": 1018, "11": 1030},
  "probabilities": {"00": 0.4970703125, "11": 0.5029296875}
}
```

---

## `GET /metrics/{job_id}?include_noise_sim=false`
Returns the "Price of Privacy" report for the job: depth overhead, total gate overhead, 2-qubit gate overhead, cutting sampling overhead, and (when `include_noise_sim=true`) ideal & noisy `qiskit-aer` TVD / Hellinger fidelity.

---

## `GET /jobs?limit=50`
Lists the most recent locally stored jobs.

---

## `POST /obfuscate`
Dry-run cloaking endpoint. Applies the requested privacy profile to an OpenQASM 3/2 circuit and returns the outbound cloaked OpenQASM 3 source and structural `CircuitOverheadMetrics` **without** executing on any backend.

---

## `DELETE /jobs/{job_id}`
Purges a job record and all associated local decoding keys (`key_bundle`, `original_qasm`, `decoded_counts`) from the SQLite WAL store (`204 No Content`).
