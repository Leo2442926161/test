from __future__ import annotations

import logging
from time import monotonic
from typing import Any

from homeassistant import config_entries
from homeassistant.components.update import UpdateEntity, UpdateEntityFeature

try:
    from homeassistant.components.update import UpdateDeviceClass
except ImportError:
    UpdateDeviceClass = None
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HeimanWifiCoordinator
from .model import (
    endpoint_device_info,
    get_endpoints,
    get_property_value,
    normalize_identifier,
)

_LOGGER = logging.getLogger(__name__)

OTA_ACTION_NAMES = (
    "ota_update",
    "update_firmware",
    "firmware_update",
    "start_ota",
    "start_update",
    "ota",
)
OTA_INFO_KEYS = ("ota", "firmwareUpdate", "firmware_update", "firmware")
OTA_ACTION_KEYS = ("action", "otaAction", "ota_action")
CURRENT_VERSION_KEYS = (
    "firmwareVersion",
    "firmware_version",
    "currentFirmwareVersion",
    "current_firmware_version",
    "currentVersion",
    "current_version",
    "version",
)
LATEST_VERSION_KEYS = (
    "latestFirmwareVersion",
    "latest_firmware_version",
    "latestVersion",
    "latest_version",
    "otaVersion",
    "ota_version",
    "availableVersion",
    "available_version",
    "targetVersion",
    "target_version",
    "version",
)
OTA_URL_KEYS = (
    "otaUrl",
    "ota_url",
    "firmwareUrl",
    "firmware_url",
    "downloadUrl",
    "download_url",
    "url",
)
OTA_MD5_KEYS = ("md5", "firmwareMd5", "firmware_md5", "checksum", "checksumMd5")
OTA_SHA256_KEYS = (
    "sha256",
    "firmwareSha256",
    "firmware_sha256",
    "checksumSha256",
    "checksum_sha256",
)
OTA_SIZE_KEYS = ("size", "firmwareSize", "firmware_size", "bytes")
RELEASE_URL_KEYS = ("releaseUrl", "release_url", "changelogUrl", "changelog_url")
RELEASE_SUMMARY_KEYS = (
    "releaseSummary",
    "release_summary",
    "releaseNotes",
    "release_notes",
    "changelog",
    "description",
)
PROGRESS_KEYS = (
    "ota.progress",
    "ota_progress",
    "update.progress",
    "update_progress",
    "firmware.progress",
    "firmware_progress",
    "update_percentage",
)
IN_PROGRESS_KEYS = (
    "ota.in_progress",
    "otaInProgress",
    "ota_in_progress",
    "update.in_progress",
    "updateInProgress",
    "update_in_progress",
    "firmware.in_progress",
    "firmwareInProgress",
    "firmware_in_progress",
)
LOCAL_PROGRESS_TIMEOUT = 30 * 60
OTA_FEATURES = UpdateEntityFeature.PROGRESS
OTA_INSTALL_FEATURES = (
    UpdateEntityFeature.INSTALL
    | getattr(UpdateEntityFeature, "SPECIFIC_VERSION", UpdateEntityFeature(0))
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: config_entries.ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: HeimanWifiCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HeimanWifiUpdate(coordinator=coordinator, entry=entry)])


class HeimanWifiUpdate(CoordinatorEntity[HeimanWifiCoordinator], UpdateEntity):
    _attr_has_entity_name = True
    _attr_supported_features = OTA_FEATURES

    def __init__(
        self,
        coordinator: HeimanWifiCoordinator,
        entry: config_entries.ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        endpoints = get_endpoints(coordinator.data, entry)
        self._endpoint = next(
            (endpoint for endpoint in endpoints if endpoint.is_root), endpoints[0]
        )
        root = normalize_identifier(entry.unique_id or entry.entry_id)
        self._attr_unique_id = f"{root}_{self._endpoint.id}_firmware"
        self._attr_name = "Firmware"

        sw_version = self._installed_version_from_data()
        self._attr_device_info = endpoint_device_info(self._endpoint, entry)
        if UpdateDeviceClass is not None:
            self._attr_device_class = UpdateDeviceClass.FIRMWARE

        self._attr_installed_version = sw_version
        self._attr_latest_version = self._latest_version_from_data() or sw_version
        self._attr_title = "Heiman Firmware"
        self._attr_in_progress = False
        self._attr_update_percentage = None
        self._attr_auto_update = False
        self._pending_version: str | None = None
        self._local_progress_started_at: float | None = None

    @property
    def installed_version(self) -> str | None:
        version = self._installed_version_from_data()
        if version:
            self._attr_installed_version = version
        return self._attr_installed_version

    @property
    def latest_version(self) -> str | None:
        version = self._latest_version_from_data()
        if version:
            self._attr_latest_version = version
        else:
            self._attr_latest_version = self.installed_version
        return self._attr_latest_version

    @property
    def supported_features(self) -> UpdateEntityFeature:
        if self._ota_supported():
            return OTA_FEATURES | OTA_INSTALL_FEATURES
        return OTA_FEATURES

    @property
    def release_url(self) -> str | None:
        return self._find_ota_value(RELEASE_URL_KEYS)

    @property
    def release_summary(self) -> str | None:
        return self._find_ota_value(RELEASE_SUMMARY_KEYS)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "ota_supported": self._ota_supported(),
        }
        if self._ota_supported():
            attrs["ota_action"] = self._ota_action()
        if ota_url := self._find_ota_value(OTA_URL_KEYS):
            attrs["ota_url"] = ota_url
        if self.coordinator.device.last_error:
            attrs["last_error"] = self.coordinator.device.last_error
        return attrs

    @property
    def in_progress(self) -> bool:
        explicit = self._ota_in_progress_from_data()
        if explicit is not None:
            if not explicit:
                self._clear_local_progress_if_complete()
            return explicit

        if self._attr_in_progress:
            self._clear_local_progress_if_complete()
            if self._attr_in_progress:
                return True
        return False

    @property
    def update_percentage(self) -> int | float | None:
        progress = self._ota_progress_from_data()
        if progress is not None:
            self._attr_update_percentage = progress
            return progress
        return self._attr_update_percentage

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_install(
        self, version: str | None = None, backup: bool = False, **kwargs: Any
    ) -> None:
        target_version = version or self.latest_version
        if not target_version:
            raise HomeAssistantError("No firmware version available for OTA update")
        if not self._ota_supported():
            actions = ", ".join(self._advertised_actions()) or "none"
            raise HomeAssistantError(
                f"{self.coordinator.device.host} does not advertise OTA support "
                f"(/info actions: {actions})"
            )

        action = self._ota_action()
        params = self._ota_params(target_version)
        device_id = None if self._endpoint.is_root else self._endpoint.id

        _LOGGER.info(
            "Starting OTA update for %s from %s to %s using action %s",
            self.coordinator.device.host,
            self.installed_version,
            target_version,
            action,
        )

        self._pending_version = target_version
        self._attr_in_progress = True
        self._local_progress_started_at = monotonic()
        self._attr_update_percentage = 0
        self.async_write_ha_state()

        ok = await self.coordinator.device.async_call_action(
            self.hass,
            action,
            device_id,
            params,
        )
        if not ok:
            self._attr_in_progress = False
            self._pending_version = None
            self._local_progress_started_at = None
            self._attr_update_percentage = None
            self.async_write_ha_state()
            detail = self.coordinator.device.last_error
            message = f"Failed to start OTA update on {self.coordinator.device.host}"
            if detail:
                message = f"{message}: {detail}"
            raise HomeAssistantError(message)

        self._attr_update_percentage = self._ota_progress_from_data() or 5
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    def _installed_version_from_data(self) -> str | None:
        info = self.coordinator.data.get("info", {})
        version = _first_string(info, CURRENT_VERSION_KEYS)
        if version:
            return version
        for ota_info in _ota_info_dicts(info):
            version = _first_string(ota_info, CURRENT_VERSION_KEYS)
            if version:
                return version
        return self._endpoint.sw_version

    def _latest_version_from_data(self) -> str | None:
        info = self.coordinator.data.get("info", {})
        version = _first_string(info, LATEST_VERSION_KEYS[:-1])
        if version:
            return version

        for ota_info in _ota_info_dicts(info):
            version = _first_string(ota_info, LATEST_VERSION_KEYS)
            if version and version != self.installed_version:
                return version

        for key in LATEST_VERSION_KEYS[:-1]:
            value = get_property_value(self.coordinator.data, self._endpoint.id, key)
            if value not in (None, ""):
                return str(value)

        state = self.coordinator.data.get("state", {})
        for container in _state_info_dicts(state):
            version = _first_string(container, LATEST_VERSION_KEYS)
            if version and version != self.installed_version:
                return version
        return None

    def _find_ota_value(self, keys: tuple[str, ...]) -> str | None:
        value = self._find_ota_raw_value(keys)
        if value in (None, ""):
            return None
        return str(value)

    def _find_ota_raw_value(self, keys: tuple[str, ...]) -> Any:
        info = self.coordinator.data.get("info", {})
        value = _first_value(info, keys)
        if value not in (None, ""):
            return value
        for ota_info in _ota_info_dicts(info):
            value = _first_value(ota_info, keys)
            if value not in (None, ""):
                return value
        return None

    def _ota_action(self) -> str:
        action = self._find_ota_value(OTA_ACTION_KEYS)
        if action:
            return action

        advertised = self._advertised_ota_action()
        if advertised:
            return advertised

        return OTA_ACTION_NAMES[0]

    def _ota_supported(self) -> bool:
        return bool(
            self._advertised_ota_action()
            or self._find_ota_value(OTA_ACTION_KEYS)
            or self._find_ota_value(OTA_URL_KEYS)
            or self._ota_metadata_available()
        )

    def _ota_metadata_available(self) -> bool:
        info = self.coordinator.data.get("info", {})
        if _first_value(info, LATEST_VERSION_KEYS[:-1]):
            return True
        for ota_info in _ota_info_dicts(info):
            if _first_value(
                ota_info,
                OTA_ACTION_KEYS + OTA_URL_KEYS + LATEST_VERSION_KEYS,
            ):
                return True
        return False

    def _advertised_ota_action(self) -> str | None:
        for action in self._advertised_actions():
            if action in OTA_ACTION_NAMES:
                return action
        return None

    def _advertised_actions(self) -> list[str]:
        actions = self.coordinator.data.get("info", {}).get("actions", [])
        results: list[str] = []
        for raw in actions if isinstance(actions, list) else []:
            if isinstance(raw, str):
                results.append(raw)
            elif isinstance(raw, dict):
                candidate = raw.get("id") or raw.get("action") or raw.get("name")
                if isinstance(candidate, str):
                    results.append(candidate)
        return results

    def _ota_params(self, target_version: str) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for ota_info in _ota_info_dicts(self.coordinator.data.get("info", {})):
            raw_params = ota_info.get("params")
            if isinstance(raw_params, dict):
                params.update(raw_params)

        params.setdefault("version", target_version)
        if ota_url := self._find_ota_value(OTA_URL_KEYS):
            params.setdefault("url", ota_url)
        if md5 := self._find_ota_value(OTA_MD5_KEYS):
            params.setdefault("md5", md5)
        if sha256 := self._find_ota_value(OTA_SHA256_KEYS):
            params.setdefault("sha256", sha256)
        size = self._find_ota_raw_value(OTA_SIZE_KEYS)
        if size not in (None, ""):
            params.setdefault("size", size)
        return params

    def _ota_progress_from_data(self) -> int | float | None:
        for key in PROGRESS_KEYS:
            value = get_property_value(self.coordinator.data, self._endpoint.id, key)
            progress = _percentage(value)
            if progress is not None:
                return progress

        for container in _state_info_dicts(self.coordinator.data.get("state", {})):
            progress = _percentage(_first_value(container, PROGRESS_KEYS))
            if progress is not None:
                return progress
        return None

    def _ota_in_progress_from_data(self) -> bool | None:
        for key in IN_PROGRESS_KEYS:
            value = get_property_value(self.coordinator.data, self._endpoint.id, key)
            explicit = _boolean(value)
            if explicit is not None:
                return explicit

        for container in _state_info_dicts(self.coordinator.data.get("state", {})):
            explicit = _boolean(_first_value(container, IN_PROGRESS_KEYS))
            if explicit is not None:
                return explicit
        return None

    def _clear_local_progress_if_complete(self) -> None:
        if not self._attr_in_progress:
            return
        if self._pending_version and self.installed_version == self._pending_version:
            self._attr_in_progress = False
        elif (
            self._local_progress_started_at is not None
            and monotonic() - self._local_progress_started_at > LOCAL_PROGRESS_TIMEOUT
        ):
            self._attr_in_progress = False

        if not self._attr_in_progress:
            self._pending_version = None
            self._local_progress_started_at = None
            self._attr_update_percentage = None


def _ota_info_dicts(info: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for key in OTA_INFO_KEYS:
        value = info.get(key)
        if isinstance(value, dict):
            results.append(value)
        elif isinstance(value, list):
            results.extend(item for item in value if isinstance(item, dict))
    return results


def _state_info_dicts(state: dict[str, Any]) -> list[dict[str, Any]]:
    results = [state]
    properties = state.get("properties")
    if isinstance(properties, dict):
        results.append(properties)
    for key in OTA_INFO_KEYS:
        value = state.get(key)
        if isinstance(value, dict):
            results.append(value)
    return results


def _first_value(container: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        current: Any = container
        for part in key.split("."):
            if not isinstance(current, dict) or part not in current:
                break
            current = current[part]
        else:
            if current not in (None, ""):
                return current
    return None


def _first_string(container: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    value = _first_value(container, keys)
    if value in (None, ""):
        return None
    return str(value)


def _percentage(value: Any) -> int | float | None:
    try:
        progress = float(value)
    except (TypeError, ValueError):
        return None
    if progress < 0:
        return 0
    if progress > 100:
        return 100
    if progress.is_integer():
        return int(progress)
    return progress


def _boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "on", "yes", "1", "running", "updating"}:
            return True
        if normalized in {"false", "off", "no", "0", "idle", "done", "complete"}:
            return False
    return None
