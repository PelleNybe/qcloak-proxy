# ruff: noqa: E501
"""Embedded zero-dependency Web Dashboard for qcloak-proxy."""

from __future__ import annotations

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="dark light" />
  <title>qcloak-proxy — Quantum Privacy Proxy Dashboard</title>
  <style>
    :root {
      --bg: #0b0f19;
      --surface: #131a2a;
      --surface-2: #1a2338;
      --border: #283552;
      --text: #e6edf7;
      --muted: #93a4c3;
      --accent: #6366f1;
      --accent-hover: #818cf8;
      --ok: #22c55e;
      --warn: #f59e0b;
      --danger: #ef4444;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      --sans: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
    }
    @media (prefers-color-scheme: light) {
      :root {
        --bg: #f4f6fb;
        --surface: #ffffff;
        --surface-2: #eef2f9;
        --border: #d0d9e8;
        --text: #111827;
        --muted: #4b5563;
        --accent: #4f46e5;
        --accent-hover: #4338ca;
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--sans);
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }
    header {
      border-bottom: 1px solid var(--border);
      background: var(--surface);
      padding: 1rem 1.5rem;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }
    .brand h1 {
      margin: 0;
      font-size: 1.25rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      padding: 0.2rem 0.6rem;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 600;
      background: var(--surface-2);
      border: 1px solid var(--border);
      color: var(--muted);
    }
    .badge.ok { color: var(--ok); border-color: color-mix(in srgb, var(--ok) 40%, transparent); }
    .badge.warn { color: var(--warn); }
    .badge.danger { color: var(--danger); }
    .header-controls {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      flex-wrap: wrap;
    }
    main {
      max-width: 1280px;
      margin: 0 auto;
      padding: 1.5rem;
      display: grid;
      gap: 1.5rem;
    }
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.25rem;
    }
    .card h2 {
      margin: 0 0 0.75rem 0;
      font-size: 1.05rem;
      font-weight: 650;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
    }
    .controls-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 0.75rem;
      margin-bottom: 1rem;
    }
    label {
      display: flex;
      flex-direction: column;
      gap: 0.3rem;
      font-size: 0.82rem;
      font-weight: 600;
      color: var(--muted);
    }
    input, select, textarea {
      font-family: inherit;
      font-size: 0.9rem;
      padding: 0.5rem 0.65rem;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: var(--surface-2);
      color: var(--text);
    }
    textarea {
      font-family: var(--mono);
      font-size: 0.82rem;
      width: 100%;
      min-height: 180px;
      resize: vertical;
    }
    .btn-row {
      display: flex;
      flex-wrap: wrap;
      gap: 0.6rem;
      margin-top: 0.75rem;
    }
    button {
      cursor: pointer;
      font-family: inherit;
      font-size: 0.86rem;
      font-weight: 600;
      padding: 0.55rem 1rem;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: var(--surface-2);
      color: var(--text);
      transition: background 0.15s ease, border-color 0.15s ease;
    }
    button:hover { border-color: var(--accent); }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #ffffff;
    }
    button.primary:hover { background: var(--accent-hover); }
    button.danger {
      color: var(--danger);
      border-color: color-mix(in srgb, var(--danger) 45%, transparent);
    }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
    .split {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 1rem;
      margin-top: 1rem;
    }
    pre {
      margin: 0;
      padding: 0.75rem;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: var(--surface-2);
      font-family: var(--mono);
      font-size: 0.8rem;
      overflow-x: auto;
      max-height: 260px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 0.75rem;
      margin-top: 0.75rem;
    }
    .stat {
      background: var(--surface-2);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.65rem 0.8rem;
    }
    .stat .k { font-size: 0.75rem; color: var(--muted); }
    .stat .v { font-size: 1.05rem; font-weight: 700; margin-top: 0.15rem; }
    .bars { display: grid; gap: 0.45rem; margin-top: 0.75rem; }
    .bar-row {
      display: grid;
      grid-template-columns: 90px 1fr 75px;
      align-items: center;
      gap: 0.6rem;
      font-family: var(--mono);
      font-size: 0.8rem;
    }
    .bar-track {
      height: 14px;
      background: var(--surface-2);
      border-radius: 999px;
      overflow: hidden;
      border: 1px solid var(--border);
    }
    .bar-fill {
      height: 100%;
      background: linear-gradient(90deg, var(--accent), #06b6d4);
      transition: width 0.35s cubic-bezier(0.22, 1, 0.36, 1);
    }
    .pulse-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: currentColor;
      display: inline-block;
      animation: qcloak-pulse 2.2s ease-in-out infinite;
    }
    @keyframes qcloak-pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.45; transform: scale(0.85); }
    }
    footer {
      max-width: 1280px;
      margin: 0 auto 1.5rem auto;
      padding: 0.75rem 1.5rem 0 1.5rem;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 0.75rem;
      font-size: 0.8rem;
      color: var(--muted);
    }
    footer a {
      color: var(--muted);
      text-decoration: none;
      border-bottom: 1px dotted var(--border);
      transition: color 0.15s ease, border-color 0.15s ease;
    }
    footer a:hover {
      color: var(--accent-hover);
      border-color: var(--accent-hover);
    }
    .table-wrap { overflow-x: auto; }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
    }
    th, td {
      text-align: left;
      padding: 0.55rem 0.65rem;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }
    th { color: var(--muted); font-weight: 600; font-size: 0.78rem; }
    td.mono { font-family: var(--mono); font-size: 0.8rem; }
    dialog {
      border: 1px solid var(--border);
      border-radius: 12px;
      background: var(--surface);
      color: var(--text);
      padding: 1.25rem;
      max-width: 420px;
    }
    dialog::backdrop { background: rgba(0, 0, 0, 0.55); }
    .muted { color: var(--muted); font-size: 0.84rem; }
    .status-msg { margin-top: 0.6rem; font-size: 0.85rem; color: var(--muted); }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <h1>qcloak-proxy</h1>
      <span id="healthBadge" class="badge">Connecting...</span>
      <span class="badge">Zero-Trust Local Key Custody</span>
    </div>
    <div class="header-controls">
      <label style="flex-direction: row; align-items: center; gap: 0.4rem;">
        <span>API Key</span>
        <input id="apiKeyInput" type="password" placeholder="Optional Bearer token" style="width: 180px;" />
      </label>
      <a href="/docs" style="color: var(--accent-hover); font-size: 0.85rem; font-weight: 600; text-decoration: none;">OpenAPI Docs</a>
    </div>
  </header>

  <main>
    <section class="card">
      <h2>
        <span>Circuit Cloaking Auditor &amp; Runner</span>
        <select id="presetSelect" aria-label="Circuit Preset" style="width: auto;">
          <option value="bell">Preset: 2Q Bell State</option>
          <option value="ghz4">Preset: 4Q GHZ State</option>
          <option value="qft3">Preset: 3Q Phase/Entangler</option>
        </select>
      </h2>

      <div class="controls-grid">
        <label>
          Backend
          <select id="backendSelect"></select>
        </label>
        <label>
          Privacy Profile
          <select id="profileSelect">
            <option value="low">low (Permutation only)</option>
            <option value="medium" selected>medium (Perm + 1Q U·U†)</option>
            <option value="high">high (Perm + 1Q &amp; 2Q U·U†)</option>
          </select>
        </label>
        <label>
          Shots
          <input id="shotsInput" type="number" min="1" max="100000" value="2048" />
        </label>
        <label>
          Circuit Cutting
          <select id="cuttingSelect">
            <option value="false" selected>Disabled</option>
            <option value="true">Enabled (qiskit-addon-cutting)</option>
          </select>
        </label>
        <label>
          Max Subcircuit Qubits
          <input id="maxSubQubits" type="number" min="1" max="16" value="2" />
        </label>
      </div>

      <label>
        OpenQASM 3 / 2 Input Circuit (never leaves your machine uncloaked)
        <textarea id="qasmInput" spellcheck="false"></textarea>
      </label>

      <div class="btn-row">
        <button id="dryRunBtn" type="button">Dry-Run Cloak (Audit)</button>
        <button id="submitBtn" type="button" class="primary">Execute via Privacy Proxy</button>
      </div>
      <div id="actionStatus" class="status-msg" role="status" aria-live="polite"></div>

      <div class="split">
        <div>
          <div class="muted" style="margin-bottom: 0.35rem;">Outbound Cloaked OpenQASM 3 (what the cloud sees)</div>
          <pre id="cloakedPreview">Click "Dry-Run Cloak (Audit)" or "Execute via Privacy Proxy" to inspect the cloaked circuit.</pre>
        </div>
        <div>
          <div class="muted" style="margin-bottom: 0.35rem;">Decoded Results &amp; Price of Privacy</div>
          <div id="metricsGrid" class="metrics-grid"></div>
          <div id="barsContainer" class="bars"></div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>
        <span>Local SQLite Key Vault &amp; Job History</span>
        <button id="refreshJobsBtn" type="button">Refresh</button>
      </h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Job ID</th>
              <th>Status</th>
              <th>Backend</th>
              <th>Profile</th>
              <th>Shots</th>
              <th>Created</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="jobsBody"></tbody>
        </table>
      </div>
    </section>
  </main>

  <dialog id="confirmPurgeDialog">
    <h3 style="margin-top: 0;">Purge Local Decoding Keys?</h3>
    <p class="muted" id="confirmPurgeText"></p>
    <div class="btn-row" style="justify-content: flex-end;">
      <button id="cancelPurgeBtn" type="button">Cancel</button>
      <button id="confirmPurgeBtn" type="button" class="danger">Purge Keys</button>
    </div>
  </dialog>

  <footer>
    <span>
      Engineered by <a href="https://coraxcolab.com" target="_blank" rel="noopener noreferrer">Corax CoLAB</a>
      &bull; Lead Developer: <a href="https://github.com/PelleNybe" target="_blank" rel="noopener noreferrer">Pelle (@PelleNybe)</a>
    </span>
    <span>
      <a href="https://buymeacoffee.com/pellenybe" target="_blank" rel="noopener noreferrer">☕ Support / Buy Me a Coffee</a>
    </span>
  </footer>

  <script>
    const PRESETS = {
      bell: `OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nbit[2] c;\nh q[0];\ncx q[0], q[1];\nc = measure q;\n`,
      ghz4: `OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[4] q;\nbit[4] c;\nh q[0];\ncx q[0], q[1];\ncx q[1], q[2];\ncx q[2], q[3];\nc = measure q;\n`,
      qft3: `OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[3] q;\nbit[3] c;\nx q[0];\nh q[1];\ncz q[0], q[1];\nh q[2];\ncx q[1], q[2];\nc = measure q;\n`
    };

    const $ = (id) => document.getElementById(id);
    let pendingPurgeJobId = null;

    function authHeaders() {
      const tok = $("apiKeyInput").value.trim();
      const headers = { "Content-Type": "application/json" };
      if (tok) headers["Authorization"] = `Bearer ${tok}`;
      return headers;
    }

    async function apiFetch(path, opts = {}) {
      const resp = await fetch(path, {
        ...opts,
        headers: { ...authHeaders(), ...(opts.headers || {}) }
      });
      if (!resp.ok) {
        let detail = resp.statusText;
        try {
          const err = await resp.json();
          detail = err.detail || JSON.stringify(err);
        } catch {}
        throw new Error(`${resp.status}: ${detail}`);
      }
      if (resp.status === 204) return null;
      return resp.json();
    }

    async function loadHealth() {
      try {
        const data = await apiFetch("/health");
        const dot = document.createElement("span");
        dot.className = "pulse-dot";
        $("healthBadge").replaceChildren(dot, document.createTextNode(` Online v${data.version}`));
        $("healthBadge").className = "badge ok";
        const sel = $("backendSelect");
        sel.replaceChildren();
        for (const b of data.backends) {
          const opt = document.createElement("option");
          opt.value = b.name;
          opt.textContent = `${b.name} (${b.backend_type})`;
          sel.appendChild(opt);
        }
      } catch (err) {
        $("healthBadge").textContent = `Offline (${err.message})`;
        $("healthBadge").className = "badge danger";
      }
    }

    function renderMetrics(overhead, idealFidelity, noisyFidelity, dummyBlocks) {
      const grid = $("metricsGrid");
      grid.replaceChildren();
      const items = [
        ["Depth", `${overhead.original_depth} -> ${overhead.obfuscated_depth} (+${overhead.depth_increase_pct}%)`],
        ["Gates", `${overhead.original_gate_count} -> ${overhead.obfuscated_gate_count} (+${overhead.gate_increase_pct}%)`],
        ["2Q Gates", `${overhead.original_two_qubit_gates} -> ${overhead.obfuscated_two_qubit_gates}`],
      ];
      if (dummyBlocks !== undefined) items.push(["Dummy Blocks", String(dummyBlocks)]);
      if (overhead.cutting_sampling_overhead) {
        items.push(["Cutting Overhead", `${overhead.cutting_sampling_overhead.toFixed(2)}x`]);
      }
      if (idealFidelity) {
        items.push(["Ideal Hellinger", idealFidelity.hellinger_fidelity.toFixed(4)]);
        items.push(["Ideal TVD", idealFidelity.total_variation_distance.toFixed(4)]);
      }
      if (noisyFidelity) {
        items.push(["Noisy Hellinger", noisyFidelity.hellinger_fidelity.toFixed(4)]);
      }
      for (const [k, v] of items) {
        const card = document.createElement("div");
        card.className = "stat";
        const kd = document.createElement("div");
        kd.className = "k";
        kd.textContent = k;
        const vd = document.createElement("div");
        vd.className = "v";
        vd.textContent = v;
        card.append(kd, vd);
        grid.appendChild(card);
      }
    }

    function renderBars(probabilities) {
      const container = $("barsContainer");
      container.replaceChildren();
      const entries = Object.entries(probabilities).sort((a, b) => b[1] - a[1]).slice(0, 16);
      for (const [bits, prob] of entries) {
        const row = document.createElement("div");
        row.className = "bar-row";
        const lbl = document.createElement("span");
        lbl.textContent = `|${bits}>`;
        const track = document.createElement("div");
        track.className = "bar-track";
        const fill = document.createElement("div");
        fill.className = "bar-fill";
        fill.style.width = `${Math.max(1, prob * 100).toFixed(1)}%`;
        track.appendChild(fill);
        const pct = document.createElement("span");
        pct.textContent = `${(prob * 100).toFixed(1)}%`;
        row.append(lbl, track, pct);
        container.appendChild(row);
      }
    }

    async function runDryRun() {
      $("actionStatus").textContent = "Cloaking locally...";
      try {
        const data = await apiFetch("/obfuscate", {
          method: "POST",
          body: JSON.stringify({
            qasm3: $("qasmInput").value,
            privacy_profile: $("profileSelect").value
          })
        });
        $("cloakedPreview").textContent = data.obfuscated_qasm3;
        renderMetrics(data.overhead, null, null, data.dummy_blocks_inserted);
        $("barsContainer").replaceChildren();
        $("actionStatus").textContent = "Dry-run cloaking complete. Nothing was sent to any backend.";
      } catch (err) {
        $("actionStatus").textContent = `Error: ${err.message}`;
      }
    }

    async function runSubmit() {
      $("actionStatus").textContent = "Cloaking and submitting to proxy...";
      try {
        const dry = await apiFetch("/obfuscate", {
          method: "POST",
          body: JSON.stringify({
            qasm3: $("qasmInput").value,
            privacy_profile: $("profileSelect").value
          })
        });
        $("cloakedPreview").textContent = dry.obfuscated_qasm3;

        const sub = await apiFetch("/submit", {
          method: "POST",
          body: JSON.stringify({
            qasm3: $("qasmInput").value,
            shots: Number($("shotsInput").value),
            backend: $("backendSelect").value,
            privacy_profile: $("profileSelect").value,
            enable_cutting: $("cuttingSelect").value === "true",
            max_subcircuit_qubits: Number($("maxSubQubits").value)
          })
        });
        await inspectJob(sub.job_id);
        await loadJobs();
      } catch (err) {
        $("actionStatus").textContent = `Error: ${err.message}`;
      }
    }

    async function inspectJob(jobId) {
      $("actionStatus").textContent = `Fetching decoded result & metrics for ${jobId}...`;
      const [res, met] = await Promise.all([
        apiFetch(`/result/${jobId}`),
        apiFetch(`/metrics/${jobId}?include_noise_sim=true`)
      ]);
      renderMetrics(met.overhead, met.ideal_fidelity, met.noisy_fidelity);
      renderBars(res.probabilities);
      $("actionStatus").textContent = `Job ${jobId} decoded (${res.shots} shots).`;
    }

    async function loadJobs() {
      try {
        const jobs = await apiFetch("/jobs?limit=25");
        const tbody = $("jobsBody");
        tbody.replaceChildren();
        for (const j of jobs) {
          const tr = document.createElement("tr");
          const cells = [
            [j.job_id, "mono"],
            [j.status, ""],
            [j.backend, ""],
            [j.privacy_profile, ""],
            [String(j.shots), ""],
            [j.created_at.slice(0, 19).replace("T", " "), "mono"]
          ];
          for (const [val, cls] of cells) {
            const td = document.createElement("td");
            if (cls) td.className = cls;
            td.textContent = val;
            tr.appendChild(td);
          }
          const actTd = document.createElement("td");
          const viewBtn = document.createElement("button");
          viewBtn.type = "button";
          viewBtn.textContent = "Inspect";
          viewBtn.addEventListener("click", () => inspectJob(j.job_id).catch((e) => {
            $("actionStatus").textContent = `Error: ${e.message}`;
          }));
          const delBtn = document.createElement("button");
          delBtn.type = "button";
          delBtn.className = "danger";
          delBtn.style.marginLeft = "0.4rem";
          delBtn.textContent = "Purge";
          delBtn.addEventListener("click", () => {
            pendingPurgeJobId = j.job_id;
            $("confirmPurgeText").textContent = `Delete job ${j.job_id} and its local decoding keys from SQLite?`;
            $("confirmPurgeDialog").showModal();
          });
          actTd.append(viewBtn, delBtn);
          tr.appendChild(actTd);
          tbody.appendChild(tr);
        }
      } catch (err) {
        $("actionStatus").textContent = `Could not load jobs: ${err.message}`;
      }
    }

    $("presetSelect").addEventListener("change", (e) => {
      $("qasmInput").value = PRESETS[e.target.value];
    });
    $("dryRunBtn").addEventListener("click", runDryRun);
    $("submitBtn").addEventListener("click", runSubmit);
    $("refreshJobsBtn").addEventListener("click", loadJobs);
    $("cancelPurgeBtn").addEventListener("click", () => $("confirmPurgeDialog").close());
    $("confirmPurgeBtn").addEventListener("click", async () => {
      if (!pendingPurgeJobId) return;
      try {
        await apiFetch(`/jobs/${pendingPurgeJobId}`, { method: "DELETE" });
        $("confirmPurgeDialog").close();
        $("actionStatus").textContent = `Purged local keys for ${pendingPurgeJobId}.`;
        await loadJobs();
      } catch (err) {
        $("actionStatus").textContent = `Error: ${err.message}`;
      }
    });

    $("qasmInput").value = PRESETS.bell;
    loadHealth().then(loadJobs);
  </script>
</body>
</html>
"""
