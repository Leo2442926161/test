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

from .const import DOMAIN
from .coordinator import HeimanWifiCoordinator
from .model import (
    HeimanEndpoint,
    HeimanProperty,
    endpoint_device_info,
    get_property_value,
    iter_properties,
    normalize_identifier,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: HeimanWifiCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        HeimanWifiSensor(coordinator=coordinator, entry=entry, endpoint=endpoint, prop=prop)
        for endpoint, prop in iter_properties(coordinator.data, entry, "sensor")
    ]
    if entities:
        async_add_entities(entities)


class HeimanWifiSensor(CoordinatorEntity[HeimanWifiCoordinator], SensorEntity):
    _attr_has_entity_name = True

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
        root = normalize_identifier(entry.unique_id or entry.entry_id)
        self._attr_unique_id = f"{root}_{endpoint.id}_{prop.key}_sensor"
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
        return self.coordinator.last_update_success
