"""Shared EVDC start-readiness guard for Sigenergy commands."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .coordinator import (
    _dc_charger_status_is_start_ready,
    _int_or_none,
    _plug_status_is_plugged_in,
    _secc_run_state_is_start_ready,
)

_START_READY_TIMEOUT = 5 * 60
_START_READY_POLL_INTERVAL = 30
_START_READY_STABLE_SECONDS = 30


@dataclass(slots=True)
class EVDCStartReadiness:
    """Latest readiness snapshot used while waiting to start an EVDC session."""

    plugged_in: bool | None
    secc_run_state: int | None
    charger_status: str | None
    ready: bool
    reason: str


async def _read_start_readiness(client: Any, dc_sn: str) -> EVDCStartReadiness:
    """Read the minimum cloud state needed to decide if EVDC start is safe."""
    plugged_in = _plug_status_is_plugged_in(
        await client.dc_plug_status(dc_sn=dc_sn)
    )
    if not plugged_in:
        return EVDCStartReadiness(
            plugged_in=plugged_in,
            secc_run_state=None,
            charger_status=None,
            ready=False,
            reason="charger plug is not reported as connected",
        )

    realtime = await client.dc_charge_realtime(dc_sn=dc_sn) or {}
    raw_secc_run_state = realtime.get("seccRunState")
    secc_run_state = _int_or_none(raw_secc_run_state)
    secc_ready = _secc_run_state_is_start_ready(raw_secc_run_state)
    if secc_ready is True:
        return EVDCStartReadiness(
            plugged_in=True,
            secc_run_state=secc_run_state,
            charger_status="Idle",
            ready=True,
            reason="SECC state is idle",
        )
    if secc_ready is False:
        return EVDCStartReadiness(
            plugged_in=True,
            secc_run_state=secc_run_state,
            charger_status=None,
            ready=False,
            reason=f"SECC state is {raw_secc_run_state}",
        )

    charger_status = await client.dc_status(dc_sn=dc_sn)
    status_ready = _dc_charger_status_is_start_ready(charger_status)
    if isinstance(charger_status, dict):
        raw_status_text = (
            charger_status.get("statusDesc")
            or charger_status.get("statusName")
            or charger_status.get("status")
        )
        charger_status_text = (
            str(raw_status_text) if raw_status_text is not None else None
        )
    else:
        charger_status_text = str(charger_status) if charger_status is not None else None

    return EVDCStartReadiness(
        plugged_in=True,
        secc_run_state=secc_run_state,
        charger_status=charger_status_text,
        ready=status_ready is True,
        reason=(
            f"charger status is {charger_status_text}"
            if charger_status_text is not None
            else "charger status is unknown"
        ),
    )


class EVDCStartReadyGate:
    """Waits for a settled EVDC ready state before issuing a start command."""

    def __init__(self, owner: Any, client: Any, dc_sn: str) -> None:
        self._owner = owner
        self._client = client
        self._dc_sn = dc_sn
        self._waiting_since: float | None = None
        self._ready_since: float | None = None
        self._snapshot: EVDCStartReadiness | None = None

    async def wait(self) -> None:
        """Block until the charger is plugged in and settled in ready/idle state."""
        deadline = time.monotonic() + _START_READY_TIMEOUT
        self._waiting_since = time.monotonic()
        self._ready_since = None
        self._snapshot = None
        self._owner.async_write_ha_state()
        try:
            while True:
                now = time.monotonic()
                self._snapshot = await _read_start_readiness(
                    self._client, self._dc_sn
                )
                if self._snapshot.ready:
                    if self._ready_since is None:
                        self._ready_since = now
                    if now - self._ready_since >= _START_READY_STABLE_SECONDS:
                        return
                else:
                    self._ready_since = None

                self._owner.async_write_ha_state()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = self._snapshot.reason if self._snapshot else "unknown"
                    raise HomeAssistantError(
                        "Sigenergy EVDC start blocked: charger did not return to a "
                        f"settled Plugged In/Idle state before timeout ({reason})."
                    )
                await asyncio.sleep(min(_START_READY_POLL_INTERVAL, remaining))
        finally:
            self._waiting_since = None
            self._ready_since = None
            self._snapshot = None
            self._owner.async_write_ha_state()

    def attributes(self) -> dict[str, Any]:
        """Return debug attributes while an EVDC start command is waiting."""
        if self._waiting_since is None:
            return {}

        attrs: dict[str, Any] = {
            "waiting_for_evdc_start_ready": True,
            "waiting_for_evdc_start_ready_seconds": int(
                time.monotonic() - self._waiting_since
            ),
            "evdc_start_ready_required_stable_seconds": _START_READY_STABLE_SECONDS,
        }
        if self._ready_since is not None:
            attrs["evdc_start_ready_stable_seconds"] = int(
                time.monotonic() - self._ready_since
            )

        snapshot = self._snapshot
        if snapshot is None:
            attrs["evdc_start_ready_reason"] = "waiting for first status read"
            return attrs

        attrs.update(
            {
                "waiting_for_plugged_in": snapshot.plugged_in is not True,
                "evdc_start_ready_plugged_in": snapshot.plugged_in,
                "evdc_start_ready_reason": snapshot.reason,
            }
        )
        if snapshot.secc_run_state is not None:
            attrs["evdc_start_ready_secc_state"] = snapshot.secc_run_state
        if snapshot.charger_status is not None:
            attrs["evdc_start_ready_charger_status"] = snapshot.charger_status
        return attrs
