from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.components.switch import SwitchEntity
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: HeimanWifiCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        HeimanWifiSwitch(coordinator=coordinator, entry=entry, endpoint=endpoint, prop=prop)
        for endpoint, prop in iter_properties(coordinator.data, entry, "switch")
    ]
    if entities:
        async_add_entities(entities)


class HeimanWifiSwitch(CoordinatorEntity[HeimanWifiCoordinator], SwitchEntity):
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
        self._attr_unique_id = f"{root}_{endpoint.id}_{prop.key}_switch"
        self._attr_name = prop.name
        self._attr_device_info = endpoint_device_info(endpoint, entry)

    @property
    def is_on(self) -> bool | None:
        value = get_property_value(self.coordinator.data, self._endpoint.id, self._prop.key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.lower() in {"on", "true", "1"}
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.device.async_set_state(
            self.hass, self._prop.key, True, self._endpoint.id
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.device.async_set_state(
            self.hass, self._prop.key, False, self._endpoint.id
        )
        await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success
