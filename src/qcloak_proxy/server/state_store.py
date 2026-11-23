"""Local SQLite (WAL-mode) state store for job metadata and decoding keys."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from pydantic import BaseModel

from qcloak_proxy.backends.base import BackendJobStatus
from qcloak_proxy.config import PrivacyProfile
from qcloak_proxy.metrics import PrivacyMetricsReport
from qcloak_proxy.obfuscation.pipeline import ObfuscationKeyBundle


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class JobRecord(BaseModel):
    """Complete local record for a proxied quantum job."""

    job_id: str
    status: BackendJobStatus
    backend_name: str
    privacy_profile: PrivacyProfile
    shots: int
    created_at: str
    updated_at: str
    original_qasm: str
    obfuscated_qasm: str
    key_bundle: ObfuscationKeyBundle | None = None
    cutting_metadata: dict[str, Any] | None = None
    backend_job_id: str | None = None
    raw_counts: dict[str, int] | None = None
    decoded_counts: dict[str, int | float] | None = None
    metrics: PrivacyMetricsReport | None = None
    error_message: str | None = None


class LocalStateStore:
    """Persistent local SQLite store configured in WAL mode.

    All sensitive artifacts (original QASM, permutation keys, cutting
    reconstruction metadata, and decoded counts) stay strictly on disk locally.
    """

    def __init__(self, db_path: Path | str, encryption_key: str | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet = self._build_fernet(encryption_key)
        self._init_schema()

    @staticmethod
    def _build_fernet(encryption_key: str | None) -> Fernet | None:
        if not encryption_key:
            return None
        try:
            return Fernet(encryption_key.encode("utf-8"))
        except Exception:
            digest = hashlib.sha256(encryption_key.encode("utf-8")).digest()
            return Fernet(base64.urlsafe_b64encode(digest))

    def _encrypt(self, plaintext: str) -> str:
        if self._fernet is None:
            return plaintext
        return "enc:" + self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def _decrypt(self, value: str) -> str:
        if self._fernet is None or not value.startswith("enc:"):
            return value
        token = value[4:].encode("ascii")
        return self._fernet.decrypt(token).decode("utf-8")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    backend_name TEXT NOT NULL,
                    privacy_profile TEXT NOT NULL,
                    shots INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    original_qasm TEXT NOT NULL,
                    obfuscated_qasm TEXT NOT NULL,
                    key_bundle_json TEXT,
                    cutting_metadata_json TEXT,
                    backend_job_id TEXT,
                    raw_counts_json TEXT,
                    decoded_counts_json TEXT,
                    metrics_json TEXT,
                    error_message TEXT
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs (created_at DESC);"
            )

    def _row_to_record(self, row: sqlite3.Row) -> JobRecord:
        key_bundle = (
            ObfuscationKeyBundle.model_validate_json(self._decrypt(row["key_bundle_json"]))
            if row["key_bundle_json"]
            else None
        )
        cutting_meta = (
            json.loads(self._decrypt(row["cutting_metadata_json"]))
            if row["cutting_metadata_json"]
            else None
        )
        raw_counts = json.loads(row["raw_counts_json"]) if row["raw_counts_json"] else None
        decoded_counts = (
            json.loads(self._decrypt(row["decoded_counts_json"]))
            if row["decoded_counts_json"]
            else None
        )
        metrics = (
            PrivacyMetricsReport.model_validate_json(row["metrics_json"])
            if row["metrics_json"]
            else None
        )
        return JobRecord(
            job_id=row["job_id"],
            status=BackendJobStatus(row["status"]),
            backend_name=row["backend_name"],
            privacy_profile=PrivacyProfile(row["privacy_profile"]),
            shots=int(row["shots"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            original_qasm=self._decrypt(row["original_qasm"]),
            obfuscated_qasm=row["obfuscated_qasm"],
            key_bundle=key_bundle,
            cutting_metadata=cutting_meta,
            backend_job_id=row["backend_job_id"],
            raw_counts=raw_counts,
            decoded_counts=decoded_counts,
            metrics=metrics,
            error_message=row["error_message"],
        )

    def create_job(self, record: JobRecord) -> None:
        """Insert a new job record into SQLite."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, status, backend_name, privacy_profile, shots,
                    created_at, updated_at, original_qasm, obfuscated_qasm,
                    key_bundle_json, cutting_metadata_json, backend_job_id,
                    raw_counts_json, decoded_counts_json, metrics_json, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    record.job_id,
                    record.status.value,
                    record.backend_name,
                    record.privacy_profile.value,
                    record.shots,
                    record.created_at,
                    record.updated_at,
                    self._encrypt(record.original_qasm),
                    record.obfuscated_qasm,
                    (
                        self._encrypt(record.key_bundle.model_dump_json())
                        if record.key_bundle
                        else None
                    ),
                    (
                        self._encrypt(json.dumps(record.cutting_metadata))
                        if record.cutting_metadata
                        else None
                    ),
                    record.backend_job_id,
                    json.dumps(record.raw_counts) if record.raw_counts is not None else None,
                    (
                        self._encrypt(json.dumps(record.decoded_counts))
                        if record.decoded_counts is not None
                        else None
                    ),
                    record.metrics.model_dump_json() if record.metrics else None,
                    record.error_message,
                ),
            )

    def get_job(self, job_id: str) -> JobRecord | None:
        """Fetch a job record by ID, or None if not found."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?;", (job_id,)).fetchone()
            return self._row_to_record(row) if row is not None else None

    def list_jobs(self, limit: int = 50) -> list[JobRecord]:
        """Return the most recent ``limit`` jobs."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?;", (limit,)
            ).fetchall()
            return [self._row_to_record(r) for r in rows]

    def update_status(
        self,
        job_id: str,
        status: BackendJobStatus,
        backend_job_id: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update job execution status and optional backend job ID / error."""
        now = _utc_now_iso()
        with self._connect() as conn:
            if backend_job_id is not None:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = ?, backend_job_id = ?, error_message = ?, updated_at = ?
                    WHERE job_id = ?;
                    """,
                    (status.value, backend_job_id, error_message, now, job_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = ?, error_message = ?, updated_at = ?
                    WHERE job_id = ?;
                    """,
                    (status.value, error_message, now, job_id),
                )

    def save_results(
        self,
        job_id: str,
        raw_counts: dict[str, int],
        decoded_counts: dict[str, int | float],
    ) -> None:
        """Persist raw and locally decoded counts and mark job COMPLETED."""
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, raw_counts_json = ?, decoded_counts_json = ?, updated_at = ?
                WHERE job_id = ?;
                """,
                (
                    BackendJobStatus.COMPLETED.value,
                    json.dumps(raw_counts),
                    self._encrypt(json.dumps(decoded_counts)),
                    now,
                    job_id,
                ),
            )

    def save_metrics(self, job_id: str, metrics: PrivacyMetricsReport) -> None:
        """Persist computed privacy & noise metrics for a job."""
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET metrics_json = ?, updated_at = ? WHERE job_id = ?;",
                (metrics.model_dump_json(), now, job_id),
            )

    def delete_job(self, job_id: str) -> bool:
        """Delete a job and all its local decoding keys. Returns True if deleted."""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM jobs WHERE job_id = ?;", (job_id,))
            return cur.rowcount > 0
