from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HeimanWifiCoordinator
from .model import (
    HeimanEndpoint,
    endpoint_available,
    endpoint_device_info,
    get_property_value,
    light_endpoints,
    normalize_identifier,
)

ON_KEYS = ("power", "on", "state", "switch")
BRIGHTNESS_KEYS = ("brightness", "bri", "level")
COLOR_TEMP_KEYS = ("color_temp_kelvin", "color_temperature", "color_temp", "ct")
RGB_KEYS = ("rgb_color", "rgb")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: HeimanWifiCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        HeimanWifiLight(coordinator=coordinator, entry=entry, endpoint=endpoint)
        for endpoint in light_endpoints(coordinator.data, entry)
    ]
    if entities:
        async_add_entities(entities)


class HeimanWifiLight(CoordinatorEntity[HeimanWifiCoordinator], LightEntity):
    _attr_has_entity_name = True
    _attr_min_color_temp_kelvin = 2000
    _attr_max_color_temp_kelvin = 6535

    def __init__(
        self,
        coordinator: HeimanWifiCoordinator,
        entry: config_entries.ConfigEntry,
        endpoint: HeimanEndpoint,
    ) -> None:
        super().__init__(coordinator)
        self._endpoint = endpoint
        root = normalize_identifier(entry.unique_id or entry.entry_id)
        self._attr_unique_id = f"{root}_{endpoint.id}_light"
        self._attr_name = endpoint.name
        self._attr_device_info = endpoint_device_info(endpoint, entry)
        modes: set[ColorMode] = set()
        if self._has_any(COLOR_TEMP_KEYS):
            modes.add(ColorMode.COLOR_TEMP)
        if self._has_any(RGB_KEYS):
            modes.add(ColorMode.RGB)
        if not modes and self._has_any(BRIGHTNESS_KEYS):
            modes.add(ColorMode.BRIGHTNESS)
        if not modes:
            modes.add(ColorMode.ONOFF)
        self._attr_supported_color_modes = modes

    def _value(self, keys: tuple[str, ...]) -> Any:
        for key in keys:
            value = get_property_value(self.coordinator.data, self._endpoint.id, key)
            if value is not None:
                return value
        return None

    def _has_any(self, keys: tuple[str, ...]) -> bool:
        raw_props = self._endpoint.raw.get("properties", [])
        if isinstance(raw_props, list):
            for prop in raw_props:
                if isinstance(prop, dict) and prop.get("id") in keys:
                    return True
        return self._value(keys) is not None

    def _first_key(self, keys: tuple[str, ...], default: str) -> str:
        raw_props = self._endpoint.raw.get("properties", [])
        if isinstance(raw_props, list):
            for prop in raw_props:
                if isinstance(prop, dict) and prop.get("id") in keys:
                    return prop["id"]
        for key in keys:
            if self._value((key,)) is not None:
                return key
        return default

    @property
    def is_on(self) -> bool | None:
        value = self._value(ON_KEYS)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.lower() in {"on", "true", "1"}
        return None

    @property
    def brightness(self) -> int | None:
        value = self._value(BRIGHTNESS_KEYS)
        if value is None:
            return None
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        if 0 <= number <= 100:
            return round(number * 255 / 100)
        return max(0, min(255, number))

    @property
    def color_temp_kelvin(self) -> int | None:
        value = self._value(COLOR_TEMP_KEYS)
        if value is None:
            return None
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        if 153 <= number <= 500:
            return round(1000000 / number)
        return number

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        value = self._value(RGB_KEYS)
        if isinstance(value, list) and len(value) >= 3:
            return tuple(max(0, min(255, int(part))) for part in value[:3])
        if isinstance(value, str):
            text = value.strip().lstrip("#")
            if len(text) == 6:
                try:
                    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))
                except ValueError:
                    return None
        return None

    @property
    def color_mode(self) -> ColorMode | None:
        if self.rgb_color is not None:
            return ColorMode.RGB
        if self.color_temp_kelvin is not None:
            return ColorMode.COLOR_TEMP
        if self.brightness is not None:
            if ColorMode.BRIGHTNESS not in self.supported_color_modes:
                if ColorMode.RGB in self.supported_color_modes:
                    return ColorMode.RGB
                if ColorMode.COLOR_TEMP in self.supported_color_modes:
                    return ColorMode.COLOR_TEMP
            return ColorMode.BRIGHTNESS
        return ColorMode.ONOFF

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.device.async_set_state(
            self.hass,
            self._first_key(ON_KEYS, "power"),
            True,
            self._endpoint.control_ids,
        )
        if ATTR_BRIGHTNESS in kwargs:
            await self.coordinator.device.async_set_state(
                self.hass,
                self._first_key(BRIGHTNESS_KEYS, "brightness"),
                kwargs[ATTR_BRIGHTNESS],
                self._endpoint.control_ids,
            )
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            await self.coordinator.device.async_set_state(
                self.hass,
                self._first_key(COLOR_TEMP_KEYS, "color_temp_kelvin"),
                kwargs[ATTR_COLOR_TEMP_KELVIN],
                self._endpoint.control_ids,
            )
        if ATTR_RGB_COLOR in kwargs:
            await self.coordinator.device.async_set_state(
                self.hass,
                self._first_key(RGB_KEYS, "rgb"),
                list(kwargs[ATTR_RGB_COLOR]),
                self._endpoint.control_ids,
            )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.device.async_set_state(
            self.hass,
            self._first_key(ON_KEYS, "power"),
            False,
            self._endpoint.control_ids,
        )
        await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        return endpoint_available(
            self.coordinator.data,
            self._endpoint.id,
            self.coordinator.last_update_success,
        )
