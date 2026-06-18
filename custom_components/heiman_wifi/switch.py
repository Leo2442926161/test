from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HeimanWifiCoordinator
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: HeimanWifiCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_unique_ids: set[str] = set()

    def add_new_entities() -> None:
        entities: list[SwitchEntity] = []
        root_endpoint = next(
            (endpoint for endpoint in get_endpoints(coordinator.data, entry) if endpoint.is_root),
            None,
        )
        if root_endpoint is not None and _supports_permit_join(coordinator.data):
            unique_id = HeimanWifiPermitJoinSwitch.make_unique_id(entry, root_endpoint)
            if unique_id not in known_unique_ids:
                known_unique_ids.add(unique_id)
                entities.append(
                    HeimanWifiPermitJoinSwitch(
                        coordinator=coordinator,
                        entry=entry,
                        endpoint=root_endpoint,
                    )
                )

        for endpoint, prop in iter_properties(coordinator.data, entry, "switch"):
            unique_id = HeimanWifiSwitch.make_unique_id(entry, endpoint, prop)
            if unique_id in known_unique_ids:
                continue
            known_unique_ids.add(unique_id)
            entities.append(
                HeimanWifiSwitch(
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


class HeimanWifiSwitch(CoordinatorEntity[HeimanWifiCoordinator], SwitchEntity):
    _attr_has_entity_name = True

    @staticmethod
    def make_unique_id(
        entry: config_entries.ConfigEntry,
        endpoint: HeimanEndpoint,
        prop: HeimanProperty,
    ) -> str:
        root = normalize_identifier(entry.unique_id or entry.entry_id)
        return f"{root}_{endpoint.id}_{prop.key}_switch"

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

    async def _async_set_power(self, value: Any) -> None:
        ok = await self.coordinator.device.async_set_state(
            self.hass, self._prop.key, value, self._endpoint.control_ids
        )
        if not ok:
            raise HomeAssistantError(
                f"Failed to set {self._prop.key} on {self._endpoint.id}"
            )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_power(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set_power(False)

    async def async_toggle(self, **kwargs: Any) -> None:
        await self._async_set_power("toggle")

    @property
    def available(self) -> bool:
        return endpoint_available(
            self.coordinator.data,
            self._endpoint.id,
            self.coordinator.last_update_success,
        )


class HeimanWifiPermitJoinSwitch(CoordinatorEntity[HeimanWifiCoordinator], SwitchEntity):
    _attr_has_entity_name = True

    @staticmethod
    def make_unique_id(
        entry: config_entries.ConfigEntry,
        endpoint: HeimanEndpoint,
    ) -> str:
        root = normalize_identifier(entry.unique_id or entry.entry_id)
        return f"{root}_{endpoint.id}_permit_join_switch"

    def __init__(
        self,
        coordinator: HeimanWifiCoordinator,
        entry: config_entries.ConfigEntry,
        endpoint: HeimanEndpoint,
    ) -> None:
        super().__init__(coordinator)
        self._endpoint = endpoint
        self._attr_unique_id = self.make_unique_id(entry, endpoint)
        self._attr_name = "Permit Join"
        self._attr_device_info = endpoint_device_info(endpoint, entry)

    @property
    def is_on(self) -> bool | None:
        value = get_property_value(self.coordinator.data, self._endpoint.id, "zigbee_joining")
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"on", "true", "1", "open", "active"}
        return None

    async def _async_set_permit_join(self, enable: bool) -> None:
        ok = await self.coordinator.device.async_call_action(
            self.hass,
            "permit_join",
            None,
            {"enable": enable},
        )
        if not ok:
            detail = self.coordinator.device.last_error
            message = "Failed to set Permit Join"
            if detail:
                message = f"{message}: {detail}"
            raise HomeAssistantError(message)
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_permit_join(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set_permit_join(False)

    @property
    def available(self) -> bool:
        return endpoint_available(
            self.coordinator.data,
            self._endpoint.id,
            self.coordinator.last_update_success,
        )


def _supports_permit_join(coordinator_data: dict[str, Any]) -> bool:
    actions = coordinator_data.get("info", {}).get("actions", [])
    return isinstance(actions, list) and "permit_join" in actions
