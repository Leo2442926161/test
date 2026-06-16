from __future__ import annotations

import logging

from homeassistant import config_entries
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    known_unique_ids: set[str] = set()

    def add_new_entities() -> None:
        entities: list[HeimanWifiBinarySensor] = []
        for endpoint, prop in iter_properties(coordinator.data, entry, "binary_sensor"):
            unique_id = HeimanWifiBinarySensor.make_unique_id(entry, endpoint, prop)
            if unique_id in known_unique_ids:
                continue
            known_unique_ids.add(unique_id)
            entities.append(
                HeimanWifiBinarySensor(
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


class HeimanWifiBinarySensor(
    CoordinatorEntity[HeimanWifiCoordinator], BinarySensorEntity
):
    _attr_has_entity_name = True

    @staticmethod
    def make_unique_id(
        entry: config_entries.ConfigEntry,
        endpoint: HeimanEndpoint,
        prop: HeimanProperty,
    ) -> str:
        root = normalize_identifier(entry.unique_id or entry.entry_id)
        return f"{root}_{endpoint.id}_{prop.key}_binary"

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
        if prop.device_class:
            try:
                self._attr_device_class = BinarySensorDeviceClass(prop.device_class)
            except ValueError:
                _LOGGER.debug("Unknown binary sensor device class: %s", prop.device_class)

    @property
    def is_on(self) -> bool | None:
        value = get_property_value(self.coordinator.data, self._endpoint.id, self._prop.key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.lower() in {"on", "open", "detected", "alarm", "true", "1"}
        return None

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success
