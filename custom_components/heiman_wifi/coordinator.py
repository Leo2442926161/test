from __future__ import annotations

import asyncio
from copy import deepcopy
from contextlib import suppress
from datetime import timedelta
import json
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HeimanWifiDevice
from .const import (
    CONF_DEVICE_TYPE,
    CONF_MAC_ADDRESS,
    CONF_MODEL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .model import normalize_identifier

_LOGGER = logging.getLogger(__name__)

RECONNECT_RETRY_INTERVAL = 10

EVENT_MESSAGE_TYPES = {
    "device_update",
    "device_removed",
    "gateway_update",
    "snapshot",
}
EVENT_PRESERVE_PROPERTIES = {
    "temperature",
}


class HeimanWifiCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for Heiman WiFi device.
    
    Uses HTTP polling to periodically fetch device state.
    Follows the Shelly pattern: mDNS discovery → HTTP info → HTTP polling for state.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device: HeimanWifiDevice,
    ) -> None:
        self.device = device
        self._event_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._removed_device_ids: set[str] = set()
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} - {entry.title}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.data = self._fallback_data()
        self.last_update_success = False

    def async_start_events(self) -> None:
        if self._event_task is None or self._event_task.done():
            self._event_task = self.hass.async_create_task(self._async_event_loop())

    def async_start_reconnect(self) -> None:
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = self.hass.async_create_task(self._async_reconnect_loop())

    async def async_startup_refresh(self) -> None:
        try:
            await self.async_refresh()
        except Exception as err:
            self.last_update_success = False
            _LOGGER.debug(
                "Initial Heiman WiFi poll for %s failed: %s",
                self.device.host,
                err,
            )
        if not self.last_update_success:
            _LOGGER.info(
                "Heiman WiFi device %s:%s unavailable during startup; "
                "the integration will keep retrying",
                self.device.host,
                self.device.port,
            )

    async def async_update_connection(self, host: str, port: int) -> None:
        if not self.device.update_connection(host, port):
            return

        _LOGGER.info("Heiman WiFi device address updated to %s:%s", host, port)
        if not self.last_update_success or not self.data:
            self.data = self._fallback_data()
        await self._async_cancel_event_task()
        self.async_start_events()
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        await self._async_cancel_event_task()
        await self._async_cancel_reconnect_task()

    async def _async_cancel_event_task(self) -> None:
        if self._event_task is None:
            return
        task = self._event_task
        self._event_task = None
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _async_cancel_reconnect_task(self) -> None:
        if self._reconnect_task is None:
            return
        task = self._reconnect_task
        self._reconnect_task = None
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            was_unavailable = not self.last_update_success
            state = await self.device.async_get_state(self.hass)
            if not state:
                detail = self.device.last_error or "empty response"
                raise UpdateFailed(f"Failed to poll /state: {detail}")
            info = await self.device.async_get_info(self.hass)
            if not info:
                detail = self.device.last_error or "empty response"
                raise UpdateFailed(f"Failed to poll /info: {detail}")
            _LOGGER.debug(
                "Polled %s: %d state devices, %d info devices",
                self.device.host,
                len(state.get("devices", [])) if isinstance(state.get("devices"), list) else 0,
                len(info.get("devices", [])) if isinstance(info.get("devices"), list) else 0,
            )
            data = {"state": state, "info": info}
            self._preserve_missing_properties(data)
            self._preserve_removed_devices(data)
            if was_unavailable:
                _LOGGER.info(
                    "Connected to Heiman WiFi device %s:%s",
                    self.device.host,
                    self.device.port,
                )
            return data
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Failed to poll device: {err}") from err

    async def _async_reconnect_loop(self) -> None:
        while True:
            try:
                if not self.last_update_success:
                    await self.async_request_refresh()
            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.debug(
                    "Heiman WiFi reconnect attempt for %s failed: %s",
                    self.device.host,
                    err,
                )
            await asyncio.sleep(RECONNECT_RETRY_INTERVAL)

    async def _async_event_loop(self) -> None:
        while True:
            try:
                ws = await self.device.async_ws_connect()
                _LOGGER.debug("Connected to %s websocket event stream", self.device.host)
                try:
                    await ws.send_json({"type": "get_snapshot"})
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._async_handle_event_message(msg.data)
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                            aiohttp.WSMsgType.CLOSE,
                        ):
                            break
                finally:
                    await ws.close()
            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.debug(
                    "Websocket event stream for %s unavailable: %s",
                    self.device.host,
                    err,
                )
            await asyncio.sleep(5)

    async def _async_handle_event_message(self, data: str) -> None:
        try:
            payload = json.loads(data)
        except ValueError:
            return
        if not isinstance(payload, dict):
            return
        message_type = payload.get("type")
        if message_type not in EVENT_MESSAGE_TYPES:
            return
        if message_type == "device_update" and self._apply_device_update(payload):
            return
        if message_type == "device_removed" and self._apply_device_removed(payload):
            await self.async_request_refresh()
            return
        await self.async_request_refresh()

    def _apply_device_update(self, payload: dict[str, Any]) -> bool:
        ha_state = payload.get("ha_state")
        if not isinstance(ha_state, dict):
            return False

        raw_device_id = ha_state.get("id") or ha_state.get("device_id") or ha_state.get("mac")
        if raw_device_id in (None, ""):
            return False
        device_id = normalize_identifier(raw_device_id)
        if device_id in self._removed_device_ids:
            if ha_state.get("online") is True:
                self._removed_device_ids.discard(device_id)
            else:
                ha_state = dict(ha_state)
                ha_state["online"] = False

        data = deepcopy(self.data or {})
        state = data.get("state")
        if not isinstance(state, dict):
            return False
        devices = state.get("devices")
        if not isinstance(devices, list):
            return False

        updated_devices: list[dict[str, Any]] = []
        found = False
        for item in devices:
            if not isinstance(item, dict):
                continue
            item_id = normalize_identifier(
                item.get("id") or item.get("device_id") or item.get("mac")
            )
            if item_id == device_id:
                merged = dict(item)
                merged["id"] = item.get("id") or raw_device_id
                if "online" in ha_state:
                    merged["online"] = ha_state["online"]
                new_props = ha_state.get("properties")
                if isinstance(new_props, dict):
                    old_props = item.get("properties")
                    merged_props = dict(new_props)
                    if isinstance(old_props, dict):
                        for key in EVENT_PRESERVE_PROPERTIES:
                            if key not in merged_props and key in old_props:
                                merged_props[key] = old_props[key]
                    merged["properties"] = merged_props
                updated_devices.append(merged)
                found = True
            else:
                updated_devices.append(item)

        if not found:
            updated_devices.append(ha_state)

        state["devices"] = updated_devices
        data["state"] = state
        self.async_set_updated_data(data)
        return True

    def _apply_device_removed(self, payload: dict[str, Any]) -> bool:
        device_id = self._removed_device_id(payload)
        if device_id is None:
            return False

        self._removed_device_ids.add(device_id)
        data = deepcopy(self.data or {})
        self._mark_device_removed(data, device_id)
        self.async_set_updated_data(data)
        return True

    def _preserve_missing_properties(self, data: dict[str, Any]) -> None:
        old_state = (self.data or {}).get("state")
        new_state = data.get("state")
        if not isinstance(old_state, dict) or not isinstance(new_state, dict):
            return
        old_devices = old_state.get("devices")
        new_devices = new_state.get("devices")
        if not isinstance(old_devices, list) or not isinstance(new_devices, list):
            return

        old_props_by_id: dict[str, dict[str, Any]] = {}
        for item in old_devices:
            if not isinstance(item, dict):
                continue
            item_id = normalize_identifier(
                item.get("id") or item.get("device_id") or item.get("mac")
            )
            props = item.get("properties")
            if item_id and isinstance(props, dict):
                old_props_by_id[item_id] = props

        for item in new_devices:
            if not isinstance(item, dict):
                continue
            item_id = normalize_identifier(
                item.get("id") or item.get("device_id") or item.get("mac")
            )
            props = item.get("properties")
            old_props = old_props_by_id.get(item_id)
            if not isinstance(props, dict) or not isinstance(old_props, dict):
                continue
            for key in EVENT_PRESERVE_PROPERTIES:
                if key not in props and key in old_props:
                    props[key] = old_props[key]

    def _preserve_removed_devices(self, data: dict[str, Any]) -> None:
        if not self._removed_device_ids:
            return

        state = data.get("state")
        if not isinstance(state, dict):
            return
        raw_devices = state.get("devices")
        if not isinstance(raw_devices, list):
            return

        for item in raw_devices:
            if not isinstance(item, dict):
                continue
            device_id = normalize_identifier(
                item.get("id") or item.get("device_id") or item.get("mac")
            )
            if device_id in self._removed_device_ids and _raw_online_value(item) is True:
                self._removed_device_ids.discard(device_id)

        for device_id in list(self._removed_device_ids):
            self._mark_device_removed(data, device_id)

    def _mark_device_removed(self, data: dict[str, Any], device_id: str) -> None:
        state = data.setdefault("state", {})
        if not isinstance(state, dict):
            return

        raw_devices = state.get("devices")
        if not isinstance(raw_devices, list):
            raw_devices = []
            state["devices"] = raw_devices

        for item in raw_devices:
            if not isinstance(item, dict):
                continue
            item_id = normalize_identifier(
                item.get("id") or item.get("device_id") or item.get("mac")
            )
            if item_id == device_id:
                item["online"] = False
                return

        raw_devices.append({"id": device_id, "online": False, "properties": {}})

    def _removed_device_id(self, payload: dict[str, Any]) -> str | None:
        payload_candidates = _removed_payload_candidates(payload)
        if not payload_candidates:
            return None

        for raw in _raw_device_dicts(self.data or {}, "info"):
            device_id = _raw_device_id(raw)
            if device_id is None:
                continue
            if _raw_device_matches_candidates(raw, payload_candidates):
                return normalize_identifier(device_id)

        for raw in _raw_device_dicts(self.data or {}, "state"):
            device_id = _raw_device_id(raw)
            if device_id is None:
                continue
            if _raw_device_matches_candidates(raw, payload_candidates):
                return normalize_identifier(device_id)

        for value in payload_candidates:
            text = normalize_identifier(value)
            if len(text) > 4:
                return text
        return None

    def _fallback_data(self) -> dict[str, Any]:
        entry_data = self.config_entry.data
        device_type = entry_data.get(CONF_DEVICE_TYPE) or "unknown"
        info: dict[str, Any] = {
            "name": self.config_entry.title,
            "type": device_type,
            "deviceType": device_type,
            "model": entry_data.get(CONF_MODEL),
            "ip": entry_data.get(CONF_HOST) or self.device.host,
            "devices": [],
            "properties": [],
        }
        if mac := entry_data.get(CONF_MAC_ADDRESS):
            info["mac"] = mac
            info["macAddress"] = mac

        return {
            "info": info,
            "state": {
                "online": False,
                "devices": [],
                "properties": {},
            },
        }


def _removed_payload_candidates(payload: dict[str, Any]) -> set[str]:
    candidates: set[str] = set()
    for key in ("id", "device_id", "deviceId", "mac", "ieee", "ieeeAddress", "ieee_address"):
        _add_candidate(candidates, payload.get(key))

    for key in ("index", "shortAddr", "short_addr"):
        value = payload.get(key)
        _add_candidate(candidates, value)
        if isinstance(value, (int, float)):
            _add_candidate(candidates, f"0x{int(value):04x}")
    return candidates


def _raw_device_dicts(coordinator_data: dict[str, Any], container_key: str) -> list[dict[str, Any]]:
    container = coordinator_data.get(container_key, {})
    if not isinstance(container, dict):
        return []
    raw_devices = container.get("devices")
    if isinstance(raw_devices, list):
        return [item for item in raw_devices if isinstance(item, dict)]
    if isinstance(raw_devices, dict):
        devices: list[dict[str, Any]] = []
        for device_id, raw in raw_devices.items():
            if isinstance(raw, dict):
                devices.append({"id": device_id, **raw})
        return devices
    return []


def _raw_device_id(raw: dict[str, Any]) -> Any:
    return (
        raw.get("id")
        or raw.get("device_id")
        or raw.get("deviceId")
        or raw.get("mac")
        or raw.get("ieee")
        or raw.get("ieeeAddress")
        or raw.get("ieee_address")
    )


def _raw_online_value(raw: dict[str, Any]) -> bool | None:
    value = raw.get("online")
    if value is None:
        props = raw.get("properties")
        if isinstance(props, dict):
            value = props.get("online")
    return _coerce_bool(value)


def _raw_device_matches_candidates(raw: dict[str, Any], candidates: set[str]) -> bool:
    values = (
        _raw_device_id(raw),
        raw.get("legacyDeviceId"),
        raw.get("legacy_device_id"),
        raw.get("index"),
        raw.get("shortAddr"),
        raw.get("short_addr"),
        raw.get("name"),
        raw.get("deviceName"),
    )
    for value in values:
        if _candidate_matches(candidates, value):
            return True
        if isinstance(value, (int, float)) and _candidate_matches(candidates, f"0x{int(value):04x}"):
            return True

    props = raw.get("properties")
    if isinstance(props, dict):
        for key in ("short_addr", "shortAddr", "index"):
            if _candidate_matches(candidates, props.get(key)):
                return True
    return False


def _candidate_matches(candidates: set[str], value: Any) -> bool:
    if value in (None, ""):
        return False
    return normalize_identifier(value) in candidates


def _add_candidate(candidates: set[str], value: Any) -> None:
    if value in (None, ""):
        return
    candidates.add(normalize_identifier(value))


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "active", "connected", "on", "online", "true", "yes"}:
            return True
        if text in {"0", "disconnected", "false", "no", "off", "offline"}:
            return False
    return None
