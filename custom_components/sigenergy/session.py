"""HTTP session helpers for Sigenergy Cloud."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import SIGENERGY_CLOUD_USER_AGENT

_USER_AGENT = "User-Agent"


def _sigenergy_headers(headers: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return request headers with a Sigenergy-compatible User-Agent."""
    merged = dict(headers or {})
    merged.setdefault(_USER_AGENT, SIGENERGY_CLOUD_USER_AGENT)
    return merged


class SigenergyCloudSession:
    """Proxy Home Assistant's shared aiohttp session with per-request headers."""

    def __init__(self, hass) -> None:
        self._session = async_get_clientsession(hass)

    def post(self, url: str, **kwargs: Any) -> Any:
        """Send POST with a User-Agent accepted by Sigenergy CloudFront."""
        kwargs["headers"] = _sigenergy_headers(kwargs.get("headers"))
        return self._session.post(url, **kwargs)

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Send request with a User-Agent accepted by Sigenergy CloudFront."""
        kwargs["headers"] = _sigenergy_headers(kwargs.get("headers"))
        return self._session.request(method, url, **kwargs)
