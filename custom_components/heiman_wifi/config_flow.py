"""Config flow for Heiman WiFi with mDNS/zeroconf discovery (Shelly-like pattern)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.zeroconf import ZeroconfServiceInfo
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from .api import HeimanWifiDevice
from .const import (
    CONF_ARCHITECTURE,
    CONF_DEVICE_TYPE,
    CONF_MAC_ADDRESS,
    CONF_MODEL,
    DEFAULT_PORT,
    DEVICE_TYPES,
    DOMAIN,
)
from .model import info_value, normalize_identifier, normalize_mac

_LOGGER = logging.getLogger(__name__)


class HeimanWifiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._port: int = DEFAULT_PORT
        self._mac: str | None = None
        self._model: str | None = None
        self._device_type: str | None = None
        self._device_name: str | None = None
        self._architecture: str | None = None
        self._info: dict[str, Any] | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._host = user_input[CONF_HOST]
            self._port = user_input.get(CONF_PORT, DEFAULT_PORT)
            return await self._async_try_connect()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                }
            ),
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        if discovery_info.ip_address.version == 6:
            return self.async_abort(reason="ipv6_not_supported")

        self._host = str(discovery_info.ip_address)
        self._port = discovery_info.port or DEFAULT_PORT

        device = HeimanWifiDevice(host=self._host, port=self._port)
        info = await device.async_get_info(self.hass)
        await device.close()

        if not info:
            return self.async_abort(reason="cannot_connect")

        self._set_info(info, discovery_info.properties)
        if self._mac:
            await self.async_set_unique_id(self._mac)
            self._abort_if_unique_id_configured(
                updates={CONF_HOST: self._host, CONF_PORT: self._port}
            )

        self.context["title_placeholders"] = {
            "name": self._device_name,
            "host": self._host,
        }

        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self._async_create_entry()

        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self._device_name,
                "host": self._host,
                "model": self._model or "Unknown",
                "device_type": self._device_type or "Unknown",
            },
        )

    async def _async_try_connect(self) -> ConfigFlowResult:
        device = HeimanWifiDevice(host=self._host, port=self._port)
        info = await device.async_get_info(self.hass)
        await device.close()

        if not info:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_HOST): str,
                        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                    }
                ),
                errors={"base": "cannot_connect"},
            )

        self._set_info(info)
        if self._mac:
            await self.async_set_unique_id(self._mac)
            self._abort_if_unique_id_configured()
        else:
            await self.async_set_unique_id(normalize_identifier(self._host))
            self._abort_if_unique_id_configured()

        return self._async_create_entry()

    def _set_info(
        self,
        info: dict[str, Any],
        zeroconf_properties: dict[str, Any] | None = None,
    ) -> None:
        self._info = info
        props = zeroconf_properties or {}
        self._mac = normalize_mac(
            info_value(info, "mac", "macAddress")
            or props.get("mac")
            or props.get("id")
        )
        self._model = info_value(info, "model", "productModel") or "Unknown"
        self._device_name = info_value(info, "name", "deviceName") or "Heiman Device"
        raw_type = info_value(info, "deviceType", "type", "typeCode") or ""
        self._device_type = DEVICE_TYPES.get(str(raw_type).upper(), str(raw_type) or "unknown")
        self._architecture = (
            info_value(info, "architecture", "networkArchitecture", "network")
            or props.get("arch")
            or "wifi"
        )

    def _async_create_entry(self) -> ConfigFlowResult:
        data = {
            CONF_HOST: self._host,
            CONF_PORT: self._port,
            CONF_MODEL: self._model or "Unknown",
            CONF_DEVICE_TYPE: self._device_type or "unknown",
            CONF_ARCHITECTURE: self._architecture or "wifi",
        }
        if self._mac:
            data[CONF_MAC_ADDRESS] = self._mac

        name = self._device_name or f"Heiman {self._model or 'Device'}"

        return self.async_create_entry(
            title=name,
            data=data,
        )
