"""Configuration and privacy profile settings for qcloak-proxy."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PrivacyProfile(StrEnum):
    """Predefined circuit obfuscation intensity profiles."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CloudProviderType(StrEnum):
    """Supported remote quantum cloud HTTP API dialects."""

    IBM_RUNTIME = "ibm_runtime"
    QASM3_RUNNER = "qasm3_runner"


class ProxySettings(BaseSettings):
    """Application settings loaded from environment variables or defaults."""

    model_config = SettingsConfigDict(
        env_prefix="QCLOAK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    privacy_profile: PrivacyProfile = Field(
        default=PrivacyProfile.MEDIUM,
        description="Default obfuscation profile applied to incoming circuits.",
    )
    db_path: Path = Field(
        default=Path("qcloak_proxy.db"),
        description="Local SQLite database path for job state and decoding keys.",
    )
    default_backend: str = Field(
        default="qcloak_aer",
        description="Default backend identifier used when none is specified.",
    )
    host: str = Field(default="127.0.0.1", description="FastAPI bind host.")
    port: int = Field(default=8000, ge=1, le=65535, description="FastAPI bind port.")
    proxy_api_key: str | None = Field(
        default=None,
        description="Optional bearer token required by the local proxy API.",
    )
    state_encryption_key: str | None = Field(
        default=None,
        description=(
            "Optional passphrase or Fernet key for encrypting sensitive local SQLite "
            "fields (original QASM, decoding keys, decoded counts) at rest."
        ),
    )
    cors_origins: list[str] = Field(
        default_factory=list,
        description="Allowed CORS origins for browser-based dashboards/clients.",
    )

    # Cloud backend adapter settings
    cloud_endpoint: str | None = Field(
        default=None,
        description="Base URL for remote cloud quantum execution API.",
    )
    cloud_api_token: str | None = Field(
        default=None,
        description="Authentication token for remote cloud quantum backend.",
    )
    cloud_provider_type: CloudProviderType = Field(
        default=CloudProviderType.QASM3_RUNNER,
        description="Remote API dialect (ibm_runtime or qasm3_runner).",
    )
    cloud_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        description="HTTP request timeout for remote cloud calls.",
    )
    cloud_max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum number of retries for transient cloud HTTP failures.",
    )

    # Circuit cutting defaults
    enable_cutting: bool = Field(
        default=False,
        description="Enable automatic circuit cutting by default.",
    )
    max_subcircuit_qubits: int = Field(
        default=3,
        ge=1,
        description="Maximum qubits per subcircuit when circuit cutting is enabled.",
    )

    # Realistic Aer noise model parameters (used for noisy simulation & metrics)
    aer_noise_depolarizing_1q: float = Field(default=0.001, ge=0.0, le=1.0)
    aer_noise_depolarizing_2q: float = Field(default=0.01, ge=0.0, le=1.0)
    aer_noise_readout_error: float = Field(default=0.015, ge=0.0, le=1.0)
