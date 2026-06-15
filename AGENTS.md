# AGENTS.md - Heiman WiFi Integration Notes

## Architecture

This is a local-only Home Assistant integration for two Heiman network
architectures:

1. Direct WiFi devices.
2. WiFi gateways with child devices behind the gateway.

The default path is zeroconf/mDNS discovery plus HTTP polling/control. MQTT is
not required.

## Discovery

`manifest.json` advertises Shelly-like zeroconf rules:

| Matcher | Purpose |
|---|---|
| `heiman*` on `_http._tcp.local.` | Standard HTTP discovery |
| `heiman*` on `_heiman._tcp.local.` | Heiman-specific discovery |

`config_flow.py::async_step_zeroconf`:

1. Rejects IPv6 discovery.
2. Connects to the IPv4 address.
3. Calls `GET /info`.
4. Normalizes `mac`/`macAddress`.
5. Uses MAC as config entry unique id and updates host/port on rediscovery.

## HTTP Contract

| Endpoint | Role |
|---|---|
| `GET /info` | Root identity, firmware, `devices[]`, property descriptors, root `actions[]` |
| `GET /state` | Root/child live state under `devices[].properties` |
| `POST /control` | `{device_id?, property, value}` writes and `{device_id?, action, params?}` actions |

Schema marker: `heiman_wifi_v1`.

## Entity Model

`model.py` converts `/info` and `/state` into:

| Object | Meaning |
|---|---|
| `HeimanEndpoint` | Root device or gateway child device |
| `HeimanProperty` | One readable/writable property under an endpoint |

HA device registry:

- Root endpoint identifier: `(heiman_wifi, <root_mac>)`.
- Child endpoint identifier: `(heiman_wifi, <child_id>)`.
- Child devices set `via_device` to the root gateway.

## Platform Routing

All platforms are loaded for every entry. Each platform creates entities only
when the model exposes matching endpoints/properties.

| Platform | Source |
|---|---|
| `light` | Endpoint type contains `light`, or property uses `platform: "light"` |
| `switch` | Property uses `platform: "switch"` or writable switch-like key |
| `binary_sensor` | Property uses `platform: "binary_sensor"` or alarm/contact key/type |
| `sensor` | Scalar read-only values, diagnostics, private scalar values |
| `button` | Root `actions[]` or `platform: "button"` properties |
| `cover` | Endpoint type contains `curtain`, `cover`, `shade`, `blind` |
| `climate` | Endpoint type contains `thermostat` or `climate` |
| `update` | Root firmware version |

## Prepared Device Types

| Type | Examples |
|---|---|
| Gateway | `GW`, `gateway` |
| Color temperature light | `CT`, `CCT`, `color_temp_light` |
| RGB light | `RGB`, `RGBCW`, `rgb_light` |
| Door/window sensor | `DO`, `door_sensor`, `contact_sensor` |
| IR controller | `IR`, `infrared_remote` |
| Temp/humidity sensor | `TH`, `temp_humid_sensor` |
| Smoke sensor | `SM`, `smoke_sensor` |
| Switch/plug | `SW`, `PL`, `smart_switch`, `smart_plug` |
| Private/custom | `private_device` |

## Services

| Service | Payload |
|---|---|
| `heiman_wifi.set_property` | `entry_id`, optional `device_id`, `property`, `value` |
| `heiman_wifi.call_action` | `entry_id`, optional `device_id`, `action` |

These are the escape hatches for private attributes and IR actions that do not
map cleanly to a first-class HA entity.

## Key Files

| File | Role |
|---|---|
| `manifest.json` | HA metadata, zeroconf and DHCP rules |
| `config_flow.py` | Manual and zeroconf setup |
| `api.py` | Local HTTP client |
| `model.py` | Root/child endpoint and property normalization |
| `coordinator.py` | Polling coordinator |
| `light.py` | On/off, brightness, color temperature, RGB lights |
| `sensor.py` | Numeric/string/private scalar sensors |
| `binary_sensor.py` | Door, smoke, gas, water, motion, tamper, alarm |
| `switch.py` | Writable switch-like properties |
| `button.py` | Actions/buttons including IR |
| `services.yaml` | Private property/action service descriptions |
| `docs/protocol-and-gateway-notes.md` | Firmware-facing protocol examples |

## Matching ESP Demo

ESP demo path:

```text
/home/leo/leo/esp/proj/study/wled_demo_integration
```

The demo advertises `heiman-sw-XXXX` and implements `/info`, `/state`, and
`/control` for a direct WiFi switch endpoint.
