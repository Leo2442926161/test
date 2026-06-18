from __future__ import annotations

from homeassistant import config_entries
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HeimanWifiCoordinator
from .model import (
    HeimanEndpoint,
    endpoint_available,
    endpoint_device_info,
    get_endpoints,
    iter_properties,
    normalize_identifier,
)

HIDDEN_ACTIONS = {"delete", "delete_device", "permit_join", "refresh"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: HeimanWifiCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_unique_ids: set[str] = set()

    def add_new_entities() -> None:
        info = coordinator.data.get("info", {})
        endpoints = get_endpoints(coordinator.data, entry)
        root_endpoint = next((endpoint for endpoint in endpoints if endpoint.is_root), None)

        buttons: list[HeimanWifiButton] = []
        if root_endpoint:
            for action in info.get("actions", []):
                if not isinstance(action, str):
                    continue
                if action in HIDDEN_ACTIONS:
                    continue
                unique_id = HeimanWifiButton.make_unique_id(entry, root_endpoint, action)
                if unique_id in known_unique_ids:
                    continue
                known_unique_ids.add(unique_id)
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
            if prop.key in HIDDEN_ACTIONS:
                continue
            unique_id = HeimanWifiButton.make_unique_id(entry, endpoint, prop.key)
            if unique_id in known_unique_ids:
                continue
            known_unique_ids.add(unique_id)
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

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


class HeimanWifiButton(CoordinatorEntity[HeimanWifiCoordinator], ButtonEntity):
    _attr_has_entity_name = True

    @staticmethod
    def make_unique_id(
        entry: config_entries.ConfigEntry,
        endpoint: HeimanEndpoint,
        action: str,
    ) -> str:
        root = normalize_identifier(entry.unique_id or entry.entry_id)
        return f"{root}_{endpoint.id}_{action}_button"

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
        self._attr_unique_id = self.make_unique_id(entry, endpoint, action)
        self._attr_name = name
        self._attr_device_info = endpoint_device_info(endpoint, entry)

    async def async_press(self) -> None:
        ok = await self.coordinator.device.async_call_action(
            self.hass, self._action, self._endpoint.control_ids
        )
        if not ok:
            detail = self.coordinator.device.last_error
            targets = ", ".join(self._endpoint.control_ids) or self._endpoint.id
            message = f"Failed to call {self._action} on {targets}"
            if detail:
                message = f"{message}: {detail}"
            raise HomeAssistantError(message)
        await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        return endpoint_available(
            self.coordinator.data,
            self._endpoint.id,
            self.coordinator.last_update_success,
        )
