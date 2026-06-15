from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HeimanWifiDevice
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class HeimanWifiCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for Heiman WiFi device.
    
    Uses HTTP polling to periodically fetch device state.
    Follows the Shelly pattern: mDNS discovery → HTTP info → HTTP polling for state.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device: HeimanWifiDevice,
    ) -> None:
        self.device = device
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} - {entry.title}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            state = await self.device.async_get_state(self.hass)
            info = await self.device.async_get_info(self.hass)
            return {"state": state, "info": info}
        except Exception as err:
            raise UpdateFailed(f"Failed to poll device: {err}") from err
