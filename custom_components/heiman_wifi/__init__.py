"""Heiman WiFi integration.

Discovery: mDNS/zeroconf (like Shelly)
  - Matches "heiman*" on _http._tcp.local. and _heiman._tcp.local.
  - Fetches device info via HTTP to determine model/type
  - Uses MAC as unique ID for deduplication

Communication: direct HTTP (local, no cloud, no MQTT broker needed)
  - Periodic polling for state updates (30s interval)
  - Direct HTTP POST for device control
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)

SERVICE_SET_PROPERTY = "set_property"
SERVICE_CALL_ACTION = "call_action"


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    hass.data.setdefault(DOMAIN, {})

    async def async_set_property(call: ServiceCall) -> None:
        entry_id = call.data["entry_id"]
        coordinator = hass.data[DOMAIN].get(entry_id)
        if coordinator is None:
            _LOGGER.warning("No Heiman WiFi config entry found for %s", entry_id)
            return
        ok = await coordinator.device.async_set_state(
            hass,
            call.data["property"],
            call.data.get("value"),
            call.data.get("device_id"),
        )
        if ok:
            await coordinator.async_request_refresh()

    async def async_call_action(call: ServiceCall) -> None:
        entry_id = call.data["entry_id"]
        coordinator = hass.data[DOMAIN].get(entry_id)
        if coordinator is None:
            _LOGGER.warning("No Heiman WiFi config entry found for %s", entry_id)
            return
        ok = await coordinator.device.async_call_action(
            hass,
            call.data["action"],
            call.data.get("device_id"),
            call.data.get("params"),
        )
        if ok:
            await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PROPERTY,
        async_set_property,
        schema=vol.Schema(
            {
                vol.Required("entry_id"): str,
                vol.Optional("device_id"): str,
                vol.Required("property"): str,
                vol.Required("value"): object,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CALL_ACTION,
        async_call_action,
        schema=vol.Schema(
            {
                vol.Required("entry_id"): str,
                vol.Optional("device_id"): str,
                vol.Required("action"): str,
                vol.Optional("params"): dict,
            }
        ),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .api import HeimanWifiDevice
    from .coordinator import HeimanWifiCoordinator

    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, 80)

    device = HeimanWifiDevice(host=host, port=port)
    coordinator = HeimanWifiCoordinator(hass=hass, entry=entry, device=device)
    entry.runtime_data = coordinator

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = entry.runtime_data

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        await coordinator.device.close()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN, None)

    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return True
