from __future__ import annotations

from homeassistant import config_entries
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HeimanWifiCoordinator
from .model import (
    HeimanEndpoint,
    endpoint_device_info,
    get_endpoints,
    iter_properties,
    normalize_identifier,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: HeimanWifiCoordinator = hass.data[DOMAIN][entry.entry_id]
    info = coordinator.data.get("info", {})
    endpoints = get_endpoints(coordinator.data, entry)
    root_endpoint = next((endpoint for endpoint in endpoints if endpoint.is_root), None)

    buttons: list[HeimanWifiButton] = []
    if root_endpoint:
        for action in info.get("actions", []):
            if isinstance(action, str):
                buttons.append(
                    HeimanWifiButton(
                        coordinator=coordinator,
                        entry=entry,
                        endpoint=root_endpoint,
                        action=action,
                        name=action.replace("_", " ").title(),
                    )
                )

    for endpoint, prop in iter_properties(coordinator.data, entry, "button"):
        buttons.append(
            HeimanWifiButton(
                coordinator=coordinator,
                entry=entry,
                endpoint=endpoint,
                action=prop.key,
                name=prop.name,
            )
        )

    if buttons:
        async_add_entities(buttons)


class HeimanWifiButton(CoordinatorEntity[HeimanWifiCoordinator], ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HeimanWifiCoordinator,
        entry: config_entries.ConfigEntry,
        endpoint: HeimanEndpoint,
        action: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._endpoint = endpoint
        self._action = action
        root = normalize_identifier(entry.unique_id or entry.entry_id)
        self._attr_unique_id = f"{root}_{endpoint.id}_{action}_button"
        self._attr_name = name
        self._attr_device_info = endpoint_device_info(endpoint, entry)

    async def async_press(self) -> None:
        await self.coordinator.device.async_call_action(
            self.hass, self._action, self._endpoint.id
        )
        await self.coordinator.async_request_refresh()
