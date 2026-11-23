# Contributing to `qcloak-proxy`

We welcome contributions from the quantum software and security community!

## Development Setup

```bash
git clone https://github.com/PelleNybe/qcloak-proxy.git
cd qcloak-proxy
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Quality Gates

Before opening a pull request, ensure all checks pass locally:

```bash
ruff check src tests
mypy src
pytest
```

## Coding Standards
- Python 3.11+ with strict type annotations (`mypy --strict` compatible).
- All Qiskit `TransformationPass` implementations must preserve the logical unitary operator and be verified with `qiskit-aer` statistical tests (TVD & Hellinger fidelity).
- Documentation, docstrings, comments, and commit messages must be written in English.
