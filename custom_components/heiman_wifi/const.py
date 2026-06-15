from __future__ import annotations

from homeassistant import const as ha_const

PERCENTAGE = getattr(ha_const, "PERCENTAGE", "%")
CONCENTRATION_PARTS_PER_MILLION = getattr(
    ha_const, "CONCENTRATION_PARTS_PER_MILLION", "ppm"
)
SIGNAL_STRENGTH_DECIBELS_MILLIWATT = getattr(
    ha_const, "SIGNAL_STRENGTH_DECIBELS_MILLIWATT", "dBm"
)

UNIT_CELSIUS = getattr(
    getattr(ha_const, "UnitOfTemperature", object),
    "CELSIUS",
    getattr(ha_const, "TEMP_CELSIUS", "\u00b0C"),
)
UNIT_VOLT = getattr(
    getattr(ha_const, "UnitOfElectricPotential", object),
    "VOLT",
    getattr(ha_const, "ELECTRIC_POTENTIAL_VOLT", "V"),
)
UNIT_WATT = getattr(
    getattr(ha_const, "UnitOfPower", object),
    "WATT",
    getattr(ha_const, "POWER_WATT", "W"),
)
UNIT_KILO_WATT_HOUR = getattr(
    getattr(ha_const, "UnitOfEnergy", object),
    "KILO_WATT_HOUR",
    getattr(ha_const, "ENERGY_KILO_WATT_HOUR", "kWh"),
)

DOMAIN = "heiman_wifi"
MANUFACTURER = "Heiman"

# Configuration
CONF_HOST = "host"
CONF_PORT = "port"
CONF_DEVICE_NAME = "device_name"
CONF_DEVICE_TYPE = "device_type"
CONF_MAC_ADDRESS = "mac_address"
CONF_MODEL = "model"
CONF_ARCHITECTURE = "architecture"

# Defaults
DEFAULT_PORT = 80
DEFAULT_SCAN_INTERVAL = 30
DISCOVERY_TIMEOUT = 30

# Device types
DEVICE_TYPE_GATEWAY = "gateway"
DEVICE_TYPE_SMOKE_SENSOR = "smoke_sensor"
DEVICE_TYPE_GAS_SENSOR = "gas_sensor"
DEVICE_TYPE_WATER_SENSOR = "water_sensor"
DEVICE_TYPE_SWITCH = "smart_switch"
DEVICE_TYPE_PLUG = "smart_plug"
DEVICE_TYPE_COLOR_TEMP_LIGHT = "color_temp_light"
DEVICE_TYPE_RGB_LIGHT = "rgb_light"
DEVICE_TYPE_TEMP_HUMID_SENSOR = "temp_humid_sensor"
DEVICE_TYPE_MOTION_SENSOR = "motion_sensor"
DEVICE_TYPE_DOOR_SENSOR = "door_sensor"
DEVICE_TYPE_IR = "infrared_remote"
DEVICE_TYPE_SIREN = "siren"
DEVICE_TYPE_CURTAIN = "curtain"
DEVICE_TYPE_THERMOSTAT = "thermostat"
DEVICE_TYPE_PRIVATE = "private_device"

DEVICE_TYPES = {
    "GW": DEVICE_TYPE_GATEWAY,
    "GATEWAY": DEVICE_TYPE_GATEWAY,
    "SM": DEVICE_TYPE_SMOKE_SENSOR,
    "SMOKE": DEVICE_TYPE_SMOKE_SENSOR,
    "GA": DEVICE_TYPE_GAS_SENSOR,
    "WA": DEVICE_TYPE_WATER_SENSOR,
    "SW": DEVICE_TYPE_SWITCH,
    "SWITCH": DEVICE_TYPE_SWITCH,
    "PL": DEVICE_TYPE_PLUG,
    "PLUG": DEVICE_TYPE_PLUG,
    "CT": DEVICE_TYPE_COLOR_TEMP_LIGHT,
    "CCT": DEVICE_TYPE_COLOR_TEMP_LIGHT,
    "RGB": DEVICE_TYPE_RGB_LIGHT,
    "RGBCW": DEVICE_TYPE_RGB_LIGHT,
    "TH": DEVICE_TYPE_TEMP_HUMID_SENSOR,
    "MO": DEVICE_TYPE_MOTION_SENSOR,
    "DO": DEVICE_TYPE_DOOR_SENSOR,
    "CONTACT": DEVICE_TYPE_DOOR_SENSOR,
    "IR": DEVICE_TYPE_IR,
    "SI": DEVICE_TYPE_SIREN,
    "CU": DEVICE_TYPE_CURTAIN,
    "TE": DEVICE_TYPE_THERMOSTAT,
}

PLATFORMS = [
    "binary_sensor",
    "button",
    "cover",
    "climate",
    "light",
    "sensor",
    "switch",
    "update",
]

PLATFORMS_BY_TYPE: dict[str, list[str]] = {
    DEVICE_TYPE_GATEWAY: PLATFORMS,
    DEVICE_TYPE_SMOKE_SENSOR: ["binary_sensor", "sensor", "button"],
    DEVICE_TYPE_GAS_SENSOR: ["binary_sensor", "sensor"],
    DEVICE_TYPE_WATER_SENSOR: ["binary_sensor", "sensor"],
    DEVICE_TYPE_SWITCH: ["switch", "sensor"],
    DEVICE_TYPE_PLUG: ["switch", "sensor"],
    DEVICE_TYPE_COLOR_TEMP_LIGHT: ["light", "sensor"],
    DEVICE_TYPE_RGB_LIGHT: ["light", "sensor"],
    DEVICE_TYPE_TEMP_HUMID_SENSOR: ["sensor"],
    DEVICE_TYPE_MOTION_SENSOR: ["binary_sensor", "sensor"],
    DEVICE_TYPE_DOOR_SENSOR: ["binary_sensor"],
    DEVICE_TYPE_IR: ["button", "sensor"],
    DEVICE_TYPE_SIREN: ["switch", "button"],
    DEVICE_TYPE_CURTAIN: ["cover"],
    DEVICE_TYPE_THERMOSTAT: ["climate", "sensor"],
    DEVICE_TYPE_PRIVATE: ["sensor", "binary_sensor", "switch", "button"],
}

SENSOR_UNIT_MAP = {
    "temperature": {
        "device_class": "temperature",
        "unit": UNIT_CELSIUS,
        "state_class": "measurement",
    },
    "humidity": {
        "device_class": "humidity",
        "unit": PERCENTAGE,
        "state_class": "measurement",
    },
    "battery": {
        "device_class": "battery",
        "unit": PERCENTAGE,
        "state_class": "measurement",
    },
    "voltage": {
        "device_class": "voltage",
        "unit": UNIT_VOLT,
        "state_class": "measurement",
    },
    "power": {
        "device_class": "power",
        "unit": UNIT_WATT,
        "state_class": "measurement",
    },
    "energy": {
        "device_class": "energy",
        "unit": UNIT_KILO_WATT_HOUR,
        "state_class": "total_increasing",
    },
    "co_concentration": {
        "device_class": "carbon_monoxide",
        "unit": CONCENTRATION_PARTS_PER_MILLION,
        "state_class": "measurement",
    },
    "signal_strength": {
        "device_class": "signal_strength",
        "unit": SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        "state_class": "measurement",
    },
    "rssi": {
        "device_class": "signal_strength",
        "unit": SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        "state_class": "measurement",
    },
}

BINARY_SENSOR_DEVICE_CLASS_MAP = {
    "smoke": "smoke",
    "Smoke": "smoke",
    "gas": "gas",
    "Gas": "gas",
    "water": "moisture",
    "Water": "moisture",
    "motion": "motion",
    "Motion": "motion",
    "door": "door",
    "Door": "door",
    "open": "door",
    "contact": "door",
    "tamper": "tamper",
    "Tamper": "tamper",
    "alarm": "problem",
    "Alarm": "problem",
    "co": "carbon_monoxide",
    "Co": "carbon_monoxide",
}
