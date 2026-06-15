from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    BINARY_SENSOR_DEVICE_CLASS_MAP,
    CONF_DEVICE_TYPE,
    CONF_MAC_ADDRESS,
    CONF_MODEL,
    DOMAIN,
    MANUFACTURER,
    SENSOR_UNIT_MAP,
)
from .helpers import info_value, normalize_identifier, normalize_mac

ROOT_STATE_KEYS = {"devices", "online", "ip", "wifi", "mqtt"}
SCALAR_TYPES = (str, int, float, bool)

SWITCH_KEYS = {"power", "switch", "relay", "outlet", "plug", "state", "on"}
LIGHT_KEYS = {
    "power",
    "on",
    "state",
    "brightness",
    "bri",
    "level",
    "color_temp",
    "color_temperature",
    "color_temp_kelvin",
    "ct",
    "rgb",
    "rgb_color",
    "hue",
    "saturation",
}
COVER_KEYS = {"position", "lift", "open", "close", "stop"}
CLIMATE_KEYS = {"temperature", "target_temperature", "heating", "hvac_mode"}
LIGHT_TYPE_HINTS = {"light", "rgb_light", "color_temp_light", "cct_light", "dimmable_light"}
COVER_TYPE_HINTS = {"curtain", "cover", "shade", "blind"}
CLIMATE_TYPE_HINTS = {"thermostat", "climate"}
SWITCH_TYPE_HINTS = {"smart_switch", "smart_plug", "switch", "plug", "siren"}
BINARY_TYPE_HINTS = {
    "smoke_sensor",
    "gas_sensor",
    "water_sensor",
    "motion_sensor",
    "door_sensor",
    "contact_sensor",
}


@dataclass(frozen=True)
class HeimanProperty:
    device_id: str
    key: str
    name: str
    platform: str
    device_class: str | None = None
    unit: str | None = None
    state_class: str | None = None
    writable: bool = False
    diagnostic: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HeimanEndpoint:
    id: str
    root_id: str
    name: str
    device_type: str
    model: str | None
    manufacturer: str
    sw_version: str | None
    is_root: bool
    properties: tuple[HeimanProperty, ...]
    raw: dict[str, Any] = field(default_factory=dict)


def root_device_id(entry: ConfigEntry, info: dict[str, Any] | None = None) -> str:
    info = info or {}
    mac = (
        normalize_mac(entry.data.get(CONF_MAC_ADDRESS))
        or normalize_mac(info_value(info, "mac", "macAddress"))
        or normalize_mac(entry.unique_id)
    )
    if mac:
        return mac
    return normalize_identifier(entry.unique_id or entry.entry_id)


def state_devices(state: dict[str, Any], root_id: str) -> dict[str, dict[str, Any]]:
    devices: dict[str, dict[str, Any]] = {}
    raw_devices = state.get("devices")

    if isinstance(raw_devices, list):
        for raw in raw_devices:
            if not isinstance(raw, dict):
                continue
            dev_id = normalize_identifier(
                raw.get("id") or raw.get("device_id") or raw.get("mac") or root_id
            )
            props = raw.get("properties")
            if not isinstance(props, dict):
                props = {
                    key: value
                    for key, value in raw.items()
                    if key not in {"id", "device_id", "mac", "name", "type", "online"}
                }
            devices[dev_id] = props
    elif isinstance(raw_devices, dict):
        for dev_id, props in raw_devices.items():
            if isinstance(props, dict):
                devices[normalize_identifier(dev_id)] = props

    root_props = state.get("properties")
    if not isinstance(root_props, dict):
        root_props = {
            key: value
            for key, value in state.items()
            if key not in ROOT_STATE_KEYS and isinstance(value, SCALAR_TYPES)
        }
    if root_props:
        devices.setdefault(root_id, {}).update(root_props)

    return devices


def get_property_value(
    coordinator_data: dict[str, Any], endpoint_id: str, key: str
) -> Any:
    state = coordinator_data.get("state", {})
    root_id = root_device_id_from_data(coordinator_data)
    devices = state_devices(state, root_id)
    props = devices.get(endpoint_id, {})

    if key in props:
        return props[key]

    current: Any = props
    for part in key.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def root_device_id_from_data(coordinator_data: dict[str, Any]) -> str:
    info = coordinator_data.get("info", {})
    mac = normalize_mac(info_value(info, "mac", "macAddress"))
    if mac:
        return mac
    return normalize_identifier(info_value(info, "id", "device_id", "deviceName", "name"))


def _raw_property_descriptors(raw_props: Any) -> dict[str, dict[str, Any]]:
    descriptors: dict[str, dict[str, Any]] = {}
    if isinstance(raw_props, list):
        for raw in raw_props:
            if isinstance(raw, str):
                descriptors[raw] = {"id": raw}
            elif isinstance(raw, dict):
                key = raw.get("id") or raw.get("key") or raw.get("code") or raw.get("property")
                if key:
                    descriptors[str(key)] = raw
    elif isinstance(raw_props, dict):
        for key, raw in raw_props.items():
            if isinstance(raw, dict):
                descriptors[str(key)] = {"id": key, **raw}
            else:
                descriptors[str(key)] = {"id": key}
    return descriptors


def _state_property_descriptors(props: dict[str, Any]) -> dict[str, dict[str, Any]]:
    descriptors: dict[str, dict[str, Any]] = {}
    for key, value in props.items():
        if key in {"private", "attributes"} and isinstance(value, dict):
            for child_key, child_value in value.items():
                if isinstance(child_value, SCALAR_TYPES):
                    descriptors[f"{key}.{child_key}"] = {"id": f"{key}.{child_key}"}
            continue
        if isinstance(value, SCALAR_TYPES):
            descriptors[str(key)] = {"id": key}
    return descriptors


def _device_type_contains(device_type: str, hints: set[str]) -> bool:
    normalized = normalize_identifier(device_type)
    return any(hint in normalized for hint in hints)


def _explicit_platform(raw: dict[str, Any]) -> str | None:
    value = raw.get("platform") or raw.get("entity") or raw.get("kind")
    if isinstance(value, str):
        value = value.lower()
        if value in {
            "sensor",
            "binary_sensor",
            "switch",
            "light",
            "cover",
            "climate",
            "button",
        }:
            return value
    return None


def _infer_platform(
    key: str,
    raw: dict[str, Any],
    value: Any,
    device_type: str,
) -> str | None:
    explicit = _explicit_platform(raw)
    if explicit:
        return explicit

    key_lower = key.lower()
    if _device_type_contains(device_type, LIGHT_TYPE_HINTS) and key_lower in LIGHT_KEYS:
        return "light"
    if _device_type_contains(device_type, COVER_TYPE_HINTS) and key_lower in COVER_KEYS:
        return "cover"
    if _device_type_contains(device_type, CLIMATE_TYPE_HINTS) and key_lower in CLIMATE_KEYS:
        return "climate"

    if key_lower in BINARY_SENSOR_DEVICE_CLASS_MAP or _device_type_contains(device_type, BINARY_TYPE_HINTS):
        if isinstance(value, (bool, int, float)) or value is None:
            return "binary_sensor"

    writable = bool(raw.get("writable") or raw.get("writeable"))
    if key_lower in SWITCH_KEYS and (
        writable or _device_type_contains(device_type, SWITCH_TYPE_HINTS)
    ):
        return "switch"

    if isinstance(value, SCALAR_TYPES) or value is None:
        return "sensor"
    return None


def _property_config(
    key: str,
    raw: dict[str, Any],
    platform: str,
) -> tuple[str | None, str | None, str | None, bool]:
    key_lower = key.lower()
    device_class = raw.get("device_class") or raw.get("deviceClass")
    unit = raw.get("unit") or raw.get("unit_of_measurement")
    state_class = raw.get("state_class") or raw.get("stateClass")
    diagnostic = bool(raw.get("diagnostic") or raw.get("entity_category") == "diagnostic")

    if platform == "sensor":
        for pattern, config in SENSOR_UNIT_MAP.items():
            if pattern in key_lower:
                device_class = device_class or config.get("device_class")
                unit = unit or config.get("unit")
                state_class = state_class or config.get("state_class")
                break
    elif platform == "binary_sensor":
        for pattern, mapped in BINARY_SENSOR_DEVICE_CLASS_MAP.items():
            if pattern in key_lower:
                device_class = device_class or mapped
                break

    return device_class, unit, state_class, diagnostic


def _build_properties(
    endpoint_id: str,
    raw_props: Any,
    state_props: dict[str, Any],
    device_type: str,
) -> tuple[HeimanProperty, ...]:
    descriptors = _state_property_descriptors(state_props)
    descriptors.update(_raw_property_descriptors(raw_props))

    props: list[HeimanProperty] = []
    for key, raw in descriptors.items():
        value = state_props.get(key)
        platform = _infer_platform(key, raw, value, device_type)
        if not platform or platform in {"light", "cover", "climate"}:
            continue
        name = raw.get("name") or raw.get("label") or key.replace("_", " ").title()
        device_class, unit, state_class, diagnostic = _property_config(key, raw, platform)
        props.append(
            HeimanProperty(
                device_id=endpoint_id,
                key=key,
                name=str(name),
                platform=platform,
                device_class=device_class,
                unit=unit,
                state_class=state_class,
                writable=bool(raw.get("writable") or raw.get("writeable")),
                diagnostic=diagnostic,
                raw=dict(raw),
            )
        )
    return tuple(props)


def get_endpoints(coordinator_data: dict[str, Any], entry: ConfigEntry) -> list[HeimanEndpoint]:
    info = coordinator_data.get("info", {})
    state = coordinator_data.get("state", {})
    root_id = root_device_id(entry, info)
    root_type = entry.data.get(CONF_DEVICE_TYPE) or info_value(info, "deviceType", "type") or "unknown"
    state_by_id = state_devices(state, root_id)

    raw_devices: list[dict[str, Any]] = []
    devices_from_info = info.get("devices")
    if isinstance(devices_from_info, list):
        raw_devices.extend(raw for raw in devices_from_info if isinstance(raw, dict))

    raw_ids = {
        normalize_identifier(raw.get("id") or raw.get("device_id") or raw.get("mac"))
        for raw in raw_devices
    }
    if root_id not in raw_ids:
        raw_devices.insert(
            0,
            {
                "id": root_id,
                "name": info_value(info, "name", "deviceName") or entry.title,
                "type": root_type,
                "model": entry.data.get(CONF_MODEL) or info_value(info, "model", "productModel"),
                "properties": info.get("properties", []),
            },
        )

    for dev_id, props in state_by_id.items():
        if dev_id not in raw_ids and dev_id != root_id:
            raw_devices.append({"id": dev_id, "name": dev_id, "type": "unknown", "properties": []})

    endpoints: list[HeimanEndpoint] = []
    seen: set[str] = set()
    for raw in raw_devices:
        endpoint_id = normalize_identifier(
            raw.get("id") or raw.get("device_id") or raw.get("mac") or root_id
        )
        if endpoint_id in seen:
            continue
        seen.add(endpoint_id)
        device_type = str(raw.get("type") or raw.get("deviceType") or root_type or "unknown")
        state_props = state_by_id.get(endpoint_id, {})
        props = _build_properties(endpoint_id, raw.get("properties", []), state_props, device_type)
        endpoints.append(
            HeimanEndpoint(
                id=endpoint_id,
                root_id=root_id,
                name=str(raw.get("name") or raw.get("deviceName") or endpoint_id),
                device_type=device_type,
                model=raw.get("model") or raw.get("productModel") or entry.data.get(CONF_MODEL),
                manufacturer=raw.get("manufacturer") or MANUFACTURER,
                sw_version=raw.get("firmwareVersion")
                or raw.get("version")
                or info_value(info, "firmwareVersion", "version"),
                is_root=endpoint_id == root_id,
                properties=props,
                raw=dict(raw),
            )
        )
    return endpoints


def endpoint_device_info(endpoint: HeimanEndpoint, entry: ConfigEntry) -> DeviceInfo:
    info: DeviceInfo = {
        "identifiers": {(DOMAIN, endpoint.id)},
        "name": endpoint.name if not endpoint.is_root else entry.title,
        "manufacturer": endpoint.manufacturer,
        "model": endpoint.model,
        "sw_version": endpoint.sw_version,
    }
    if not endpoint.is_root:
        info["via_device"] = (DOMAIN, endpoint.root_id)
    return info


def iter_properties(
    coordinator_data: dict[str, Any], entry: ConfigEntry, platform: str
) -> list[tuple[HeimanEndpoint, HeimanProperty]]:
    return [
        (endpoint, prop)
        for endpoint in get_endpoints(coordinator_data, entry)
        for prop in endpoint.properties
        if prop.platform == platform
    ]


def light_endpoints(coordinator_data: dict[str, Any], entry: ConfigEntry) -> list[HeimanEndpoint]:
    endpoints = []
    state = coordinator_data.get("state", {})
    root_id = root_device_id_from_data(coordinator_data)
    state_by_id = state_devices(state, root_id)
    for endpoint in get_endpoints(coordinator_data, entry):
        props = state_by_id.get(endpoint.id, {})
        has_light_property = any(
            _explicit_platform(raw) == "light"
            for raw in _raw_property_descriptors(endpoint.raw.get("properties", [])).values()
        )
        if (
            _device_type_contains(endpoint.device_type, LIGHT_TYPE_HINTS)
            or has_light_property
            or any(key.lower() in {"rgb", "rgb_color", "color_temp", "color_temperature"} for key in props)
        ):
            endpoints.append(endpoint)
    return endpoints


def cover_endpoints(coordinator_data: dict[str, Any], entry: ConfigEntry) -> list[HeimanEndpoint]:
    return [
        endpoint
        for endpoint in get_endpoints(coordinator_data, entry)
        if _device_type_contains(endpoint.device_type, COVER_TYPE_HINTS)
    ]


def climate_endpoints(coordinator_data: dict[str, Any], entry: ConfigEntry) -> list[HeimanEndpoint]:
    return [
        endpoint
        for endpoint in get_endpoints(coordinator_data, entry)
        if _device_type_contains(endpoint.device_type, CLIMATE_TYPE_HINTS)
    ]
