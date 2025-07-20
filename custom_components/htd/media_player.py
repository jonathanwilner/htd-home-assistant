"""Support for HTD"""

import logging
import re

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
)
from homeassistant.components.media_player.const import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_UNIQUE_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from htd_client import BaseClient, HtdConstants, HtdMcaClient
from htd_client.models import ZoneDetail

from .const import CONF_DEVICE_NAME, DOMAIN


def make_alphanumeric(input_string):
    """Make a string alphanumeric, suitable for entity IDs."""
    temp = re.sub(r"[^a-zA-Z0-9]", "_", input_string)
    return re.sub(r"_+", "_", temp).strip("_")


def get_media_player_entity_id(name, zone_number, zone_fmt):
    """Generate a media player entity ID."""
    return f"media_player.{make_alphanumeric(name)}_zone_{zone_number:{zone_fmt}}".lower()


SUPPORT_HTD = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
)

_LOGGER = logging.getLogger(__name__)

HtdClientConfigEntry = ConfigEntry[BaseClient]


async def async_setup_platform(hass, _, async_add_entities, __=None):
    """Set up the HTD platform from configuration.yaml."""
    htd_configs = hass.data[DOMAIN]
    entities = []

    for device_index in range(len(htd_configs)):
        config = htd_configs[device_index]

        unique_id = config[CONF_UNIQUE_ID]
        device_name = config[CONF_DEVICE_NAME]
        client = config["client"]

        zone_count = client.get_zone_count()
        source_count = client.get_source_count()
        sources = [f"Source {i + 1}" for i in range(source_count)]
        for zone in range(1, zone_count + 1):
            entity = HtdDevice(unique_id, device_name, zone, sources, client)

            entities.append(entity)

    async_add_entities(entities)

    return True


async def async_setup_entry(
    _: HomeAssistant,
    config_entry: HtdClientConfigEntry,
    async_add_entities,
):
    """Set up the HTD platform from a config entry."""
    entities = []

    client = config_entry.runtime_data
    zone_count = client.get_zone_count()
    source_count = client.get_source_count()
    device_name = config_entry.title
    unique_id = config_entry.data.get(CONF_UNIQUE_ID)
    sources = [f"Source {i + 1}" for i in range(source_count)]
    for zone in range(1, zone_count + 1):
        entity = HtdDevice(unique_id, device_name, zone, sources, client)

        entities.append(entity)

    async_add_entities(entities)


class HtdDevice(MediaPlayerEntity):
    """Representation of an HTD-MC zone."""

    should_poll = False

    _attr_supported_features = SUPPORT_HTD
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_media_content_type = MediaType.MUSIC

    device_name: str = None
    client: BaseClient = None
    sources: [str] = None
    zone: int = None
    zone_info: ZoneDetail = None
    _attr_volume_level: float | None = None
    _attr_is_volume_muted: bool | None = None
    _attr_source: str | None = None

    def __init__(self, unique_id, device_name, zone, sources, client):
        """Initialize the HTD device."""
        self._attr_unique_id = f"{unique_id}_{zone:02}"
        self.device_name = device_name
        self.zone = zone
        self.client = client
        self.sources = sources
        zone_fmt = "02" if self.client.model["zones"] > 10 else "01"
        self.entity_id = get_media_player_entity_id(device_name, zone, zone_fmt)

    @property
    def enabled(self) -> bool:
        """Return true if the entity is enabled."""
        return self.zone_info is not None and self.zone_info.enabled

    @property
    def name(self):
        """Return the name of the zone."""
        return f"Zone {self.zone} ({self.device_name})"

    def update(self):
        """Update the state of the device."""
        self.zone_info = self.client.get_zone(self.zone)
        self._update_properties()

    @property
    def state(self) -> MediaPlayerState | str:
        """Return the state of the device."""
        if not self.client.connected:
            return STATE_UNAVAILABLE

        if self.zone_info is None:
            return STATE_UNKNOWN

        if self.zone_info.power:
            return MediaPlayerState.PLAYING

        return MediaPlayerState.OFF

    @property
    def volume_step(self) -> float:
        """Return the volume step."""
        return 1 / HtdConstants.MAX_VOLUME

    async def async_volume_up(self) -> None:
        """Turn volume up for the zone."""
        await self.client.async_volume_up(self.zone)

    async def async_volume_down(self) -> None:
        """Turn volume down for the zone."""
        await self.client.async_volume_down(self.zone)

    async def async_media_play(self) -> None:
        """Send play command."""
        await self.client.async_power_on(self.zone)

    async def async_media_pause(self) -> None:
        """Send pause command."""
        await self.client.async_power_off(self.zone)

    async def async_media_stop(self) -> None:
        """Send stop command."""
        await self.client.async_power_off(self.zone)

    @property
    def volume_level(self) -> float | None:
        """Return the volume level of the device."""
        return self._attr_volume_level

    @property
    def available(self) -> bool:
        """Return true if the device is available."""
        return self.client.ready and self.zone_info is not None

    async def async_set_volume_level(self, volume: float):
        """Set the volume level."""
        converted_volume = int(volume * HtdConstants.MAX_VOLUME)
        _LOGGER.info(
            "setting new volume for zone %d to %f, raw htd = %d",
            self.zone,
            volume,
            converted_volume,
        )
        await self.client.async_set_volume(self.zone, converted_volume)

    @property
    def is_volume_muted(self) -> bool | None:
        """Return true if the device is muted."""
        return self._attr_is_volume_muted

    async def async_mute_volume(self, mute):
        """Mute or unmute the device."""
        if mute:
            await self.client.async_mute(self.zone)
        else:
            await self.client.async_unmute(self.zone)

    @property
    def source(self) -> str | None:
        """Return the current input source."""
        return self._attr_source

    @property
    def source_list(self):
        """Return a list of available input sources."""
        return self.sources

    @property
    def media_title(self):
        """Return the current media title."""
        return self.source

    async def async_select_source(self, source: str):
        """Select an input source."""
        source_index = self.sources.index(source)
        await self.client.async_set_source(self.zone, source_index + 1)

    @property
    def icon(self):
        """Return the icon to use in the frontend."""
        return "mdi:disc-player"

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        await self.client.async_subscribe(self._do_update)
        self.client.refresh()

    async def async_will_remove_from_hass(self):
        """Entity being removed from hass."""
        await self.client.async_unsubscribe(self._do_update)

    def _update_properties(self) -> None:
        """Update entity attributes from the latest zone information."""
        if self.zone_info is None:
            self._attr_volume_level = None
            self._attr_is_volume_muted = None
            self._attr_source = None
            return

        self._attr_volume_level = self.zone_info.volume / HtdConstants.MAX_VOLUME
        self._attr_is_volume_muted = self.zone_info.mute
        try:
            self._attr_source = self.sources[self.zone_info.source - 1]
        except (IndexError, TypeError):
            self._attr_source = None

    def _do_update(self, zone: int):
        """Update the entity with new data from the client."""
        if zone is None and self.zone_info is not None:
            return

        if zone is not None and zone != 0 and zone != self.zone:
            return

        if not self.client.has_zone_data(self.zone):
            return

        # If there's a target volume for mca, don't update yet
        if isinstance(self.client, HtdMcaClient) and self.client.has_volume_target(
            self.zone
        ):
            return

        if zone is not None and self.client.has_zone_data(zone):
            self.zone_info = self.client.get_zone(zone)
            self._update_properties()
            self.schedule_update_ha_state(force_refresh=True)
