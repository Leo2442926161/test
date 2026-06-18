# Heiman WiFi for Home Assistant

Heiman WiFi is a local Home Assistant custom integration for Heiman direct WiFi
devices and Heiman gateways. The discovery path is Shelly-like: devices announce
themselves with zeroconf/mDNS, Home Assistant fetches `/info`, then interacts
with the device through local HTTP.

## What Users Need

1. Install this repository with HACS.
2. Restart Home Assistant.
3. Provision a Heiman WiFi device to the same LAN.
4. Home Assistant discovers it automatically under Devices & Services.

No MQTT broker and no cloud service are required for the default path.

## Supported Architectures

| Architecture | HA config entry | Device topology |
|---|---|---|
| Direct WiFi device | One config entry per WiFi device | Root endpoint only |
| Gateway device | One config entry per gateway | Gateway root endpoint plus child endpoints |
 
Both architectures use the same HTTP contract:

| Endpoint | Purpose |
|---|---|
| `GET /info` | Identity, model, firmware, topology, property descriptors |
| `GET /state` | Current values for root and child devices |
| `POST /control` | Property writes and action calls |
 
## Discovery

The integration declares two zeroconf matchers:

```json
[
  {"name": "heiman*", "type": "_http._tcp.local."},
  {"name": "heiman*", "type": "_heiman._tcp.local."}
]
```

When a service appears, `config_flow.py` connects to the IPv4 address, calls
`GET /info`, normalizes the MAC address, and stores it as the unique id. This
deduplicates duplicate `_http` and `_heiman` discoveries and keeps the entry
stable if the device IP changes.

## Entity Mapping

The integration reads `devices[]` from `/info` and values from `/state`.

| HA platform | Source |
|---|---|
| `light` | Endpoint type contains `light`, or a property uses `platform: "light"` |
| `switch` | Property uses `platform: "switch"` or is a writable switch-like key |
| `binary_sensor` | Property uses `platform: "binary_sensor"` or matches alarm/contact keys |
| `sensor` | Scalar read-only values, diagnostics, and private scalar values |
| `button` | Root `actions[]` or properties marked `platform: "button"` |
| `cover` | Endpoint type contains `curtain`, `cover`, `shade`, or `blind` |
| `climate` | Endpoint type contains `thermostat` or `climate` |
| `update` | Root firmware version and optional OTA metadata |

Child devices are registered as HA devices with `via_device` pointing back to
the gateway root device.

Gateway child availability is driven by the child item's top-level `online`
field in `GET /state`. The integration does not create an `Online` entity for
each child; it uses that value to mark existing child entities as available or
unavailable in the native Home Assistant way.

Home Assistant does not expose child-device delete/remove buttons. Network
removal should be initiated by the gateway firmware, gateway maintenance UI, or
the physical device leave flow. When the gateway reports a child leave/remove
event over `/ws` as `device_removed`, the integration matches it by child id,
`index`, or `shortAddr` and marks the matching child endpoint offline. HA may
keep old entity registry entries after a real delete; remove stale entities from
the HA device page if they are no longer needed.

For gateway child devices, the integration keeps the state/registry identity
separate from the `device_id` sent to `/control`. When firmware exposes multiple
child identifiers, command routing prefers explicit `control_id` or `device_id`
values, then falls back through `id`, `mac`/`ieee`, and finally the child name.
If a gateway returns `device_not_found`, the integration retries the next
candidate. This matters for firmware that treats child ids as case-sensitive or
uses a display-style id such as `HS2_Water_70AC08FF` for control.

Water leak devices accept common alarm state strings such as `wet`, `leak`,
`leaking`, `flood`, `triggered`, and `alarm` as active states. Strings such as
`dry`, `clear`, `ok`, `normal`, and `no_alarm` are treated as inactive. Numeric
alarm values still use `0` as clear and non-zero as active.

Temperature properties named `temperature`, `temp`, `temp_*`, or
`*_temperature` are mapped as temperature sensors even when they appear on a
water leak or other binary-sensor style endpoint.

If a gateway web page shows alarm or temperature values but Home Assistant does
not, check the gateway HA API shape rather than only the dashboard snapshot.
Home Assistant creates entities from `GET /info`, polls `GET /state` every 30
seconds, and for WS6GW also listens to `/ws` event messages when available.
Fast child-device updates should include `ha_state` in websocket
`device_update` messages so HA can update without waiting for the next poll.
Values that exist only in the dashboard-only `device.state` object are not
enough for HA entities.

The integration opens LAN HTTP connections with proxy environment variables
disabled. If `curl http://<gateway>.local/state` returns a proxy error such as
HTTP 503, retry with `curl --noproxy '*' http://<gateway>.local/state`; Home
Assistant should see the same direct response after the integration is updated
and restarted.

## Device Types Prepared

| Device | Type examples | HA platforms |
|---|---|---|
| Gateway | `GW`, `gateway` | sensor, binary_sensor, switch, light, button, cover, climate, update |
| Water leak sensor | `WA`, `water_sensor` | binary_sensor, sensor |
| Color temperature light | `CT`, `CCT`, `color_temp_light` | light |
| RGB light | `RGB`, `RGBCW`, `rgb_light` | light |
| Door/window sensor | `DO`, `door_sensor`, `contact_sensor` | binary_sensor, sensor |
| IR controller | `IR`, `infrared_remote` | button, sensor, services |
| Temperature/humidity | `TH`, `temp_humid_sensor` | sensor |
| Smoke sensor | `SM`, `smoke_sensor` | binary_sensor, sensor, button |
| Switch/plug | `SW`, `PL`, `smart_switch`, `smart_plug` | switch, sensor |
| Private/custom device | `private_device` | sensor, binary_sensor, switch, button |

## Services

### `heiman_wifi.set_property`

Writes any property supported by the firmware, including private properties.

```yaml
service: heiman_wifi.set_property
data:
  entry_id: 01J...
  device_id: light_rgb_01
  property: rgb
  value: [255, 0, 0]
```

For a direct/root device, `device_id` can be omitted.

### `heiman_wifi.call_action`

Calls actions such as `identify`, `learn_ir`, `send_ir`, `reset`, or `mute`.

```yaml
service: heiman_wifi.call_action
data:
  entry_id: 01J...
  device_id: ir_01
  action: send_ir
  params:
    code: "..."
```

### `heiman_wifi.install_firmware`

Starts a firmware OTA install without relying on `/info` OTA metadata. This is
useful during development when you already have a firmware image available over
HTTP.

```yaml
service: heiman_wifi.install_firmware
data:
  entry_id: 01J...
  version: "1.0.2"
  url: "http://192.168.1.10/firmware.bin"
```

For a direct/root device, `device_id` can be omitted. The default action is
`ota_update`; set `action` if the firmware uses a different OTA action name.
Extra values such as `md5`, `sha256`, or `size` can be passed under `params`.

## Firmware OTA

The update entity reads the installed version from `firmwareVersion` or
`version`. To make Home Assistant show an available OTA update, include OTA
metadata in `/info`:

```json
{
  "firmwareVersion": "1.0.0",
  "ota": {
    "latest_version": "1.0.1",
    "url": "http://192.168.1.10/firmware.bin",
    "sha256": "optional-image-sha256",
    "size": 524288,
    "action": "ota_update",
    "release_summary": "Stability fixes"
  },
  "actions": ["ota_update"]
}
```

When Install is pressed, HA calls `/control` with:

```json
{
  "action": "ota_update",
  "params": {
    "version": "1.0.1",
    "url": "http://192.168.1.10/firmware.bin",
    "sha256": "optional-image-sha256",
    "size": 524288
  }
}
```

The install action is only enabled when `/info` advertises OTA metadata or an
OTA action. Root-device OTA actions are sent without `device_id`; child-device
actions include `device_id`.

The firmware should return a non-2xx HTTP status, or a JSON response such as
`{"ok": false, "error": "reason"}`, when OTA cannot start. The integration
treats that as a failed install and shows the device error in HA.

Progress can be reported from `/state`:

```json
{
  "ota": {
    "in_progress": true,
    "progress": 42
  }
}
```

When the device reboots into the new firmware and `/info.firmwareVersion`
matches the target version, the integration clears local progress state.

## Installation

### HACS

1. HACS -> Integrations.
2. Add this repository as a custom repository if it is not in the default list.
3. Install `Heiman WiFi`.
4. Restart Home Assistant.

### Manual

Copy `custom_components/heiman_wifi` into Home Assistant's `custom_components`
directory and restart Home Assistant.

## Publishing Notes

HACS validation also checks GitHub repository metadata. Before running the HACS
publish action, make sure the repository has a description and topics configured
in the GitHub About panel.

### HACS update prompts and release tags

Home Assistant does not check `manifest.json` for custom integration updates by
itself. The `version` field only tells Home Assistant and HACS which version is
installed. Update prompts for the integration are handled by HACS, so the
integration must be installed and tracked through HACS rather than copied
manually into `custom_components`.

Before publishing a new integration update:

1. Update `custom_components/heiman_wifi/manifest.json` to the new version.
2. Commit the release changes.
3. Create and push a tag that matches the manifest version.
4. Create a GitHub release from that tag.
5. In HACS, use the repository menu action `Update information`, or wait for
   the next HACS refresh.

Example:

```bash
VERSION=1.2.7
git add custom_components/heiman_wifi README.md
git commit -m "Release v$VERSION"
git tag -a "v$VERSION" -m "Heiman WiFi v$VERSION"
git push origin main
git push origin "v$VERSION"
```

Replace `main` with the release branch if needed. When testing update prompts,
the version installed in Home Assistant must be lower than the version published
on GitHub; otherwise HACS correctly treats the integration as already current.

Suggested description:

```text
Local Home Assistant integration for Heiman WiFi devices and gateways
```

Suggested topics. Add them one by one in the GitHub About panel; do not paste
the code fence, commas, or labels such as `Home Assistant`.

```text
home-assistant
hacs
integration
custom-component
heiman
wifi
iot
```

## Development Files

| File | Role |
|---|---|
| `custom_components/heiman_wifi/manifest.json` | HA metadata and zeroconf rules |
| `custom_components/heiman_wifi/config_flow.py` | Manual and zeroconf config flow |
| `custom_components/heiman_wifi/api.py` | HTTP client for `/info`, `/state`, `/control` |
| `custom_components/heiman_wifi/model.py` | Shared root/child endpoint and property model |
| `custom_components/heiman_wifi/coordinator.py` | 30 second local polling |
| `custom_components/heiman_wifi/light.py` | On/off, brightness, color temperature, RGB lights |
| `custom_components/heiman_wifi/sensor.py` | Numeric/string/private scalar values |
| `custom_components/heiman_wifi/binary_sensor.py` | Door, smoke, gas, water, motion, tamper, alarm |
| `custom_components/heiman_wifi/switch.py` | Writable switch-like properties |
| `custom_components/heiman_wifi/button.py` | Actions and button-like properties |
| `custom_components/heiman_wifi/services.yaml` | Private property/action service definitions |

See [docs/protocol-and-gateway-notes.md](docs/protocol-and-gateway-notes.md)
for the firmware-facing protocol examples. See
[docs/ws6gw-ha-change-notes.md](docs/ws6gw-ha-change-notes.md) for the WS6GW
gateway capability mapping, water-leak notes, and recent change log.

## ESP Demo

The matching ESP32-C3 demo firmware is in:

```text
/home/leo/leo/esp/proj/study/wled_demo_integration
```

It advertises `heiman-sw-XXXX`, implements `/info`, `/state`, `/control`, and
can be built with the ESP-IDF flow documented in that project's README.

## License

MIT
