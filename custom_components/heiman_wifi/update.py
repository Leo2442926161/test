from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HeimanWifiCoordinator
from .model import endpoint_device_info, get_endpoints, normalize_identifier

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: HeimanWifiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [HeimanWifiUpdate(coordinator=coordinator, entry=entry)]
    )


class HeimanWifiUpdate(CoordinatorEntity[HeimanWifiCoordinator], UpdateEntity):
    _attr_has_entity_name = True
    _attr_supported_features = UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS

    def __init__(
        self,
        coordinator: HeimanWifiCoordinator,
        entry: config_entries.ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        endpoints = get_endpoints(coordinator.data, entry)
        self._endpoint = next((endpoint for endpoint in endpoints if endpoint.is_root), endpoints[0])
        root = normalize_identifier(entry.unique_id or entry.entry_id)
        self._attr_unique_id = f"{root}_{self._endpoint.id}_firmware"
        self._attr_name = "Firmware"

        info = coordinator.data.get("info", {})
        sw_version = info.get("firmwareVersion") or info.get("version")
        self._attr_device_info = endpoint_device_info(self._endpoint, entry)

        self._attr_installed_version = sw_version
        self._attr_latest_version = sw_version
        self._attr_title = "Heiman Firmware"
        self._attr_in_progress = False
        self._attr_update_percentage = None

    @property
    def installed_version(self) -> str | None:
        info = self.coordinator.data.get("info", {})
        version = info.get("firmwareVersion") or info.get("version")
        if version:
            self._attr_installed_version = version
        return self._attr_installed_version

    @property
    def latest_version(self) -> str | None:
        return self.installed_version

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_install(
        self, version: str | None = None, backup: bool = False
    ) -> None:
        _LOGGER.info("Firmware update triggered for %s", self.coordinator.device.host)
