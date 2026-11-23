"""QCloakProvider: 1-line drop-in Qiskit provider for qcloak-proxy."""

from __future__ import annotations

import httpx

from qcloak_proxy.config import PrivacyProfile
from qcloak_proxy.provider.backend import QCloakBackend


class QCloakProvider:
    """Qiskit provider plugin connecting to a local or remote ``qcloak-proxy`` server.

    Example:
        >>> from qcloak_proxy.provider import QCloakProvider
        >>> backend = QCloakProvider("http://localhost:8000").get_backend("qcloak_aer")
    """

    def __init__(
        self,
        proxy_url: str = "http://127.0.0.1:8000",
        api_key: str | None = None,
        privacy_profile: PrivacyProfile = PrivacyProfile.MEDIUM,
        client: httpx.Client | None = None,
    ) -> None:
        self.proxy_url = proxy_url.rstrip("/")
        self.api_key = api_key
        self.privacy_profile = privacy_profile

        if client is not None:
            self._client = client
            self._owns_client = False
        else:
            headers: dict[str, str] = {"Accept": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            self._client = httpx.Client(
                base_url=self.proxy_url,
                headers=headers,
                timeout=30.0,
            )
            self._owns_client = True

    def close(self) -> None:
        """Close the underlying HTTP client if owned by this provider."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> QCloakProvider:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def backends(self) -> list[QCloakBackend]:
        """Discover and return all backends registered on the proxy server."""
        resp = self._client.get("/health")
        resp.raise_for_status()
        data = resp.json()
        backend_list = data.get("backends", [])
        return [
            QCloakBackend(
                proxy_url=self.proxy_url,
                backend_name=str(item["name"]),
                num_qubits=int(item.get("num_qubits", 28)),
                api_key=self.api_key,
                privacy_profile=self.privacy_profile,
                client=self._client,
            )
            for item in backend_list
        ]

    def get_backend(self, name: str = "qcloak_aer") -> QCloakBackend:
        """Retrieve a specific ``QCloakBackend`` by name."""
        try:
            for backend in self.backends():
                if backend.name == name:
                    return backend
        except httpx.HTTPError:
            # Allow lazy instantiation if server isn't up yet
            return QCloakBackend(
                proxy_url=self.proxy_url,
                backend_name=name,
                api_key=self.api_key,
                privacy_profile=self.privacy_profile,
                client=self._client,
            )
        raise KeyError(f"Backend '{name}' not found on qcloak-proxy at {self.proxy_url}")
