from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, UNIT_CELSIUS
from .coordinator import HeimanWifiCoordinator
from .model import (
    HeimanEndpoint,
    climate_endpoints,
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
        HeimanWifiClimate(coordinator=coordinator, entry=entry, endpoint=endpoint)
        for endpoint in climate_endpoints(coordinator.data, entry)
    ]
    if entities:
        async_add_entities(entities)


class HeimanWifiClimate(CoordinatorEntity[HeimanWifiCoordinator], ClimateEntity):
    _attr_has_entity_name = True
    _attr_temperature_unit = UNIT_CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_target_temperature_step = 1.0
    _attr_min_temp = 5.0
    _attr_max_temp = 35.0

    def __init__(
        self,
        coordinator: HeimanWifiCoordinator,
        entry: config_entries.ConfigEntry,
        endpoint: HeimanEndpoint,
    ) -> None:
        super().__init__(coordinator)
        self._endpoint = endpoint
        root = normalize_identifier(entry.unique_id or entry.entry_id)
        self._attr_unique_id = f"{root}_{endpoint.id}_climate"
        self._attr_name = endpoint.name
        self._attr_device_info = endpoint_device_info(endpoint, entry)

    @property
    def current_temperature(self) -> float | None:
        value = get_property_value(self.coordinator.data, self._endpoint.id, "temperature")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @property
    def target_temperature(self) -> float | None:
        value = get_property_value(
            self.coordinator.data, self._endpoint.id, "target_temperature"
        )
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @property
    def hvac_mode(self) -> HVACMode:
        mode = get_property_value(self.coordinator.data, self._endpoint.id, "hvac_mode")
        if isinstance(mode, str) and mode.lower() == HVACMode.HEAT:
            return HVACMode.HEAT
        heating = get_property_value(self.coordinator.data, self._endpoint.id, "heating")
        return HVACMode.HEAT if heating else HVACMode.OFF

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.coordinator.device.async_set_state(
            self.hass, "heating", hvac_mode == HVACMode.HEAT, self._endpoint.id
        )
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.coordinator.device.async_set_state(
            self.hass, "target_temperature", temperature, self._endpoint.id
        )
        await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success
