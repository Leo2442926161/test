from __future__ import annotations

from collections.abc import Sequence
import json
import logging
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)


class HeimanWifiDevice:
    """Representation of a Heiman WiFi device."""

    def __init__(self, host: str, port: int = 80) -> None:
        self.host = host
        self.port = port
        self._base_url = f"http://{host}:{port}"
        self._info: dict[str, Any] | None = None
        self._session: aiohttp.ClientSession | None = None
        self.last_error: str | None = None
        self.last_response: str | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def async_get_info(self, hass: HomeAssistant | None = None) -> dict[str, Any]:
        session = await self._get_session() if hass is None else async_get_clientsession(hass)
        try:
            async with session.get(f"{self._base_url}/info", timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._info = data
                    return data
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Failed to get info from %s: %s", self.host, err)
        return {}

    async def async_get_state(self, hass: HomeAssistant) -> dict[str, Any]:
        session = async_get_clientsession(hass)
        try:
            async with session.get(f"{self._base_url}/state", timeout=10) as resp:
                if resp.status == 200:
                    return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Failed to get state from %s: %s", self.host, err)
        return {}

    async def async_set_state(
        self,
        hass: HomeAssistant,
        property_id: str,
        value: Any,
        device_id: str | Sequence[str] | None = None,
    ) -> bool:
        payload: dict[str, Any] = {"property": property_id, "value": value}
        return await self._async_post_control_candidates(
            hass, payload, device_id, f"set {property_id}"
        )

    async def async_call_action(
        self,
        hass: HomeAssistant,
        action: str,
        device_id: str | Sequence[str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> bool:
        payload: dict[str, Any] = {"action": action}
        if params:
            payload["params"] = params
        return await self._async_post_control_candidates(
            hass, payload, device_id, f"call action {action}"
        )

    async def _async_post_control_candidates(
        self,
        hass: HomeAssistant,
        payload: dict[str, Any],
        device_id: str | Sequence[str] | None,
        operation: str,
    ) -> bool:
        candidates = _device_id_candidates(device_id)
        for index, candidate in enumerate(candidates):
            candidate_payload = dict(payload)
            if candidate:
                candidate_payload["device_id"] = candidate
            ok = await self._async_post_control(hass, candidate_payload, operation)
            if ok:
                return True
            if index == len(candidates) - 1 or not self._last_error_is_device_not_found():
                return False
            _LOGGER.debug(
                "Retrying %s on %s with alternate device_id after device_not_found",
                operation,
                self.host,
            )
        return False

    async def _async_post_control(
        self,
        hass: HomeAssistant,
        payload: dict[str, Any],
        operation: str,
    ) -> bool:
        session = async_get_clientsession(hass)
        self.last_error = None
        self.last_response = None
        try:
            async with session.post(
                f"{self._base_url}/control",
                json=payload,
                timeout=10,
            ) as resp:
                body = await resp.text()
                self.last_response = body
                data = _json_body(body)
                if not 200 <= resp.status < 300:
                    self.last_error = f"HTTP {resp.status}: {body}"
                    _LOGGER.error(
                        "Failed to %s on %s with HTTP %s: %s",
                        operation,
                        self.host,
                        resp.status,
                        body,
                    )
                    return False
                if isinstance(data, dict) and data.get("ok") is False:
                    error = data.get("error") or data.get("message") or body
                    self.last_error = f"Device rejected request: {error}"
                    _LOGGER.error(
                        "Device rejected %s on %s: %s",
                        operation,
                        self.host,
                        error,
                    )
                    return False
                if isinstance(data, dict) and data.get("success") is False:
                    error = data.get("error") or data.get("message") or body
                    self.last_error = f"Device rejected request: {error}"
                    _LOGGER.error(
                        "Device rejected %s on %s: %s",
                        operation,
                        self.host,
                        error,
                    )
                    return False
                return True
        except (aiohttp.ClientError, TimeoutError) as err:
            self.last_error = str(err)
            _LOGGER.error("Failed to %s on %s: %s", operation, self.host, err)
        return False

    @property
    def mac(self) -> str | None:
        if self._info:
            return self._info.get("mac") or self._info.get("macAddress")
        return None

    @property
    def model(self) -> str | None:
        if self._info:
            return self._info.get("model") or self._info.get("productModel")
        return None

    @property
    def device_type(self) -> str | None:
        if self._info:
            return self._info.get("type") or self._info.get("deviceType")
        return None

    @property
    def firmware_version(self) -> str | None:
        if self._info:
            return self._info.get("firmwareVersion") or self._info.get("version")
        return None

    @property
    def device_name(self) -> str | None:
        if self._info:
            return self._info.get("name") or self._info.get("deviceName")
        return None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _last_error_is_device_not_found(self) -> bool:
        return "device_not_found" in (self.last_response or self.last_error or "")


def _device_id_candidates(device_id: str | Sequence[str] | None) -> tuple[str | None, ...]:
    if device_id is None or isinstance(device_id, str):
        return (device_id,)

    results: list[str | None] = []
    seen: set[str] = set()
    for value in device_id:
        if value in (None, ""):
            continue
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        results.append(text)
    return tuple(results) or (None,)


def _json_body(body: str) -> Any:
    if not body:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None
