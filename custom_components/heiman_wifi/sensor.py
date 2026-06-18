from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HOST, CONF_MAC_ADDRESS, DOMAIN
from .coordinator import HeimanWifiCoordinator
from .helpers import info_value, normalize_mac
from .model import (
    HeimanEndpoint,
    HeimanProperty,
    endpoint_available,
    endpoint_device_info,
    get_endpoints,
    get_property_value,
    iter_properties,
    normalize_identifier,
)

_LOGGER = logging.getLogger(__name__)

INFO_SENSOR_DESCRIPTIONS = (
    ("ip_address", "IP Address"),
    ("mac_address", "MAC Address"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: HeimanWifiCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_unique_ids: set[str] = set()

    def add_new_entities() -> None:
        entities: list[SensorEntity] = []
        root_endpoint = next(
            (endpoint for endpoint in get_endpoints(coordinator.data, entry) if endpoint.is_root),
            None,
        )
        if root_endpoint is not None:
            for key, name in INFO_SENSOR_DESCRIPTIONS:
                unique_id = HeimanWifiInfoSensor.make_unique_id(entry, root_endpoint, key)
                if unique_id in known_unique_ids:
                    continue
                known_unique_ids.add(unique_id)
                entities.append(
                    HeimanWifiInfoSensor(
                        coordinator=coordinator,
                        entry=entry,
                        endpoint=root_endpoint,
                        key=key,
                        name=name,
                    )
                )

        for endpoint, prop in iter_properties(coordinator.data, entry, "sensor"):
            unique_id = HeimanWifiSensor.make_unique_id(entry, endpoint, prop)
            if unique_id in known_unique_ids:
                continue
            known_unique_ids.add(unique_id)
            entities.append(
                HeimanWifiSensor(
                    coordinator=coordinator,
                    entry=entry,
                    endpoint=endpoint,
                    prop=prop,
                )
            )
        if entities:
            async_add_entities(entities)

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


class HeimanWifiSensor(CoordinatorEntity[HeimanWifiCoordinator], SensorEntity):
    _attr_has_entity_name = True

    @staticmethod
    def make_unique_id(
        entry: config_entries.ConfigEntry,
        endpoint: HeimanEndpoint,
        prop: HeimanProperty,
    ) -> str:
        root = normalize_identifier(entry.unique_id or entry.entry_id)
        return f"{root}_{endpoint.id}_{prop.key}_sensor"

    def __init__(
        self,
        coordinator: HeimanWifiCoordinator,
        entry: config_entries.ConfigEntry,
        endpoint: HeimanEndpoint,
        prop: HeimanProperty,
    ) -> None:
        super().__init__(coordinator)
        self._endpoint = endpoint
        self._prop = prop
        self._attr_unique_id = self.make_unique_id(entry, endpoint, prop)
        self._attr_name = prop.name
        self._attr_device_info = endpoint_device_info(endpoint, entry)
        if prop.diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._apply_config(prop)

    def _apply_config(self, prop: HeimanProperty) -> None:
        if prop.device_class:
            try:
                self._attr_device_class = SensorDeviceClass(prop.device_class)
            except ValueError:
                _LOGGER.debug("Unknown sensor device class: %s", prop.device_class)
        if prop.unit:
            self._attr_native_unit_of_measurement = prop.unit
        if prop.state_class:
            try:
                self._attr_state_class = SensorStateClass(prop.state_class)
            except ValueError:
                _LOGGER.debug("Unknown sensor state class: %s", prop.state_class)

    @property
    def native_value(self) -> str | int | float | None:
        value = get_property_value(self.coordinator.data, self._endpoint.id, self._prop.key)
        if self._prop.key == "zigbee_join_detected":
            return "detected" if _truthy(value) else "clear"
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (dict, list)):
            return None
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "heiman_device_id": self._endpoint.id,
            "heiman_property": self._prop.key,
        }

    @property
    def available(self) -> bool:
        return endpoint_available(
            self.coordinator.data,
            self._endpoint.id,
            self.coordinator.last_update_success,
        )


class HeimanWifiInfoSensor(CoordinatorEntity[HeimanWifiCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @staticmethod
    def make_unique_id(
        entry: config_entries.ConfigEntry,
        endpoint: HeimanEndpoint,
        key: str,
    ) -> str:
        root = normalize_identifier(entry.unique_id or entry.entry_id)
        return f"{root}_{endpoint.id}_{key}_sensor"

    def __init__(
        self,
        coordinator: HeimanWifiCoordinator,
        entry: config_entries.ConfigEntry,
        endpoint: HeimanEndpoint,
        key: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._endpoint = endpoint
        self._key = key
        self._attr_unique_id = self.make_unique_id(entry, endpoint, key)
        self._attr_name = name
        self._attr_device_info = endpoint_device_info(endpoint, entry)

    @property
    def native_value(self) -> str | None:
        info = self.coordinator.data.get("info", {})
        if self._key == "ip_address":
            value = (
                info_value(info, "ip", "ipAddress", "ip_address")
                or self._entry.data.get(CONF_HOST)
                or self.coordinator.device.host
            )
            return str(value) if value not in (None, "") else None

        if self._key == "mac_address":
            value = (
                info_value(info, "mac", "macAddress")
                or self._entry.data.get(CONF_MAC_ADDRESS)
            )
            return _display_mac(value)

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "heiman_device_id": self._endpoint.id,
            "heiman_property": self._key,
        }

    @property
    def available(self) -> bool:
        return endpoint_available(
            self.coordinator.data,
            self._endpoint.id,
            self.coordinator.last_update_success,
        )


def _display_mac(value: Any) -> str | None:
    normalized = normalize_mac(value)
    if normalized and len(normalized) == 12:
        return ":".join(normalized[index : index + 2] for index in range(0, 12, 2)).upper()
    if value in (None, ""):
        return None
    return str(value)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "active", "detected", "on", "true", "yes"}
    return False
