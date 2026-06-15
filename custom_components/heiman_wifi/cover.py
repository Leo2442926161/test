from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HeimanWifiCoordinator
from .model import (
    HeimanEndpoint,
    cover_endpoints,
    endpoint_device_info,
    get_property_value,
    normalize_identifier,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: HeimanWifiCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        HeimanWifiCover(coordinator=coordinator, entry=entry, endpoint=endpoint)
        for endpoint in cover_endpoints(coordinator.data, entry)
    ]
    if entities:
        async_add_entities(entities)


class HeimanWifiCover(CoordinatorEntity[HeimanWifiCoordinator], CoverEntity):
    _attr_has_entity_name = True
    _attr_device_class = CoverDeviceClass.CURTAIN
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(
        self,
        coordinator: HeimanWifiCoordinator,
        entry: config_entries.ConfigEntry,
        endpoint: HeimanEndpoint,
    ) -> None:
        super().__init__(coordinator)
        self._endpoint = endpoint
        root = normalize_identifier(entry.unique_id or entry.entry_id)
        self._attr_unique_id = f"{root}_{endpoint.id}_cover"
        self._attr_name = endpoint.name
        self._attr_device_info = endpoint_device_info(endpoint, entry)

    @property
    def is_closed(self) -> bool | None:
        pos = self.current_cover_position
        if pos is not None:
            return pos == 0
        return None

    @property
    def current_cover_position(self) -> int | None:
        value = get_property_value(self.coordinator.data, self._endpoint.id, "position")
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self.coordinator.device.async_set_state(
            self.hass, "position", 100, self._endpoint.id
        )
        await self.coordinator.async_request_refresh()

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self.coordinator.device.async_set_state(
            self.hass, "position", 0, self._endpoint.id
        )
        await self.coordinator.async_request_refresh()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        position = kwargs.get("position")
        if position is None:
            return
        await self.coordinator.device.async_set_state(
            self.hass, "position", position, self._endpoint.id
        )
        await self.coordinator.async_request_refresh()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.coordinator.device.async_set_state(
            self.hass, "stop", True, self._endpoint.id
        )
        await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success
