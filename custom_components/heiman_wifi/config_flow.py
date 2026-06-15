"""Config flow for Heiman WiFi with mDNS/zeroconf discovery (Shelly-like pattern)."""

from __future__ import annotations

import logging
from ipaddress import ip_address
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import (
    CONF_ARCHITECTURE,
    CONF_DEVICE_TYPE,
    CONF_MAC_ADDRESS,
    CONF_MODEL,
    DEFAULT_PORT,
    DEVICE_TYPES,
    DOMAIN,
)
from .helpers import info_value, normalize_identifier, normalize_mac

ConfigFlowResult = dict[str, Any]

_LOGGER = logging.getLogger(__name__)


def _discovery_attr(discovery_info: Any, key: str) -> Any:
    if isinstance(discovery_info, dict):
        return discovery_info.get(key)
    return getattr(discovery_info, key, None)


def _discovery_host(discovery_info: Any) -> tuple[str | None, bool]:
    raw_host = _discovery_attr(discovery_info, "ip_address")
    if raw_host is None:
        raw_host = _discovery_attr(discovery_info, "host")
    if raw_host is None:
        raw_host = _discovery_attr(discovery_info, "hostname")
    if raw_host is None:
        return None, False

    if getattr(raw_host, "version", None) == 6:
        return str(raw_host), True

    host = str(raw_host).strip("[]")
    try:
        parsed = ip_address(host)
    except ValueError:
        return host, False

    return str(parsed), parsed.version == 6


def _discovery_port(discovery_info: Any) -> int:
    port = _discovery_attr(discovery_info, "port")
    if port in (None, ""):
        return DEFAULT_PORT
    try:
        return int(port)
    except (TypeError, ValueError):
        return DEFAULT_PORT


def _discovery_properties(discovery_info: Any) -> dict[str, Any]:
    properties = _discovery_attr(discovery_info, "properties")
    if isinstance(properties, dict):
        return dict(properties)
    return {}


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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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

    async def async_step_zeroconf(self, discovery_info: Any) -> ConfigFlowResult:
        host, is_ipv6 = _discovery_host(discovery_info)
        if is_ipv6:
            return self.async_abort(reason="ipv6_not_supported")
        if host is None:
            return self.async_abort(reason="cannot_connect")

        self._host = host
        self._port = _discovery_port(discovery_info)

        info = await self._async_get_info()

        if not info:
            return self.async_abort(reason="cannot_connect")

        self._set_info(info, _discovery_properties(discovery_info))
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
        info = await self._async_get_info()

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

    async def _async_get_info(self) -> dict[str, Any]:
        if self._host is None:
            return {}

        device = None
        try:
            from .api import HeimanWifiDevice

            device = HeimanWifiDevice(host=self._host, port=self._port)
            return await device.async_get_info(self.hass)
        except Exception:
            _LOGGER.exception(
                "Failed to load Heiman WiFi info from %s:%s",
                self._host,
                self._port,
            )
            return {}
        finally:
            if device is not None:
                await device.close()

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
        self._device_type = DEVICE_TYPES.get(
            str(raw_type).upper(), str(raw_type) or "unknown"
        )
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
