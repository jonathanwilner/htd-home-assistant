"""Support for HTD"""

import logging
import re

from homeassistant.components.media_player import MediaPlayerEntity, MediaPlayerDeviceClass
from homeassistant.components.media_player.const import MediaPlayerEntityFeature, MediaType
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_UNIQUE_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNKNOWN,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from htd_client import BaseClient, HtdConstants, HtdMcaClient
from htd_client.models import ZoneDetail

from .const import DOMAIN, CONF_DEVICE_NAME


def make_alphanumeric(input_string):
    temp = re.sub(r'[^a-zA-Z0-9]', '_', input_string)
    return re.sub(r'_+', '_', temp).strip('_')

get_media_player_entity_id = lambda name, zone_number, zone_fmt: f"media_player.{make_alphanumeric(name)}_zone_{zone_number:{zone_fmt}}".lower()

SUPPORT_HTD = (
    MediaPlayerEntityFeature.SELECT_SOURCE |
    MediaPlayerEntityFeature.TURN_OFF |
    MediaPlayerEntityEntityFeature.TURN_ON |
    MediaPlayerEntityFeature.VOLUME_MUTE |
    MediaPlayerEntityFeature.VOLUME_SET |
    MediaPlayerEntityFeature.VOLUME_STEP |
    MediaPlayerEntityFeature.PLAY |
    MediaPlayerEntityFeature.PAUSE |
    MediaPlayerEntityFeature.STOP
)

_LOGGER = logging.getLogger(__name__)

HtdClientConfigEntry = ConfigEntry[BaseClient]


async def async_setup_platform(hass, _, async_add_entities, __=None):
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
            entity = HtdDevice(
                unique_id,
                device_name,
                zone,
                sources,
                client
            )

            entities.append(entity)

    async_add_entities(entities)

    return True


async def async_setup_entry(_: HomeAssistant, config_entry: HtdClientConfigEntry, async_add_entities):
    entities = []

    client = config_entry.runtime_data
    zone_count = client.get_zone_count()
    source_count = client.get_source_count()
    device_name = config_entry.title
    unique_id = config_entry.data.get(CONF_UNIQUE_ID)
    sources = [f"Source {i + 1}" for i in range(source_count)]
    for zone in range(1, zone_count + 1):
        entity = HtdDevice(
            unique_id,
            device_name,
            zone,
            sources,
            client
        )

        entities.append(entity)

    async_add_entities(entities)



class HtdDevice(MediaPlayerEntity):
    should_poll = False

    _attr_supported_features = SUPPORT_HTD
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_media_content_type = MediaType.MUSIC


    device_name: str = None
    client: BaseClient = None
    sources: [str] = None
    zone: int = None
    changing_volume: int | None = None
    zone_info: ZoneDetail = None
    _attr_volume_level: float | None = None
    _attr_is_volume_muted: bool | None = None
    _attr_source: str | None = None

    def __init__(
        self,
        unique_id,
        device_name,
        zone,
        sources,
        client
    ):
        self._attr_unique_id = f"{unique_id}_{zone:02}"
        self.device_name = device_name
        self.zone = zone
        self.client = client
        self.sources = sources
        zone_fmt = f"02" if self.client.model["zones"] > 10 else "01"
        self.entity_id = get_media_player_entity_id(device_name, zone, zone_fmt)

    @property
    def enabled(self) -> bool:
        return self.zone_info is not None and self.zone_info.enabled


    @property
    def name(self):
        return f"Zone {self.zone} ({self.device_name})"

    def update(self):
        # This method is not used as should_poll is False.
        # State updates are handled via _do_update callback.
        pass

    @property
    def state(self):
        if not self.client.connected:
            return STATE_UNAVAILABLE

        if self.zone_info is None:
            return STATE_UNKNOWN

        if self.zone_info.power:
            return STATE_ON

        return STATE_OFF

    @property
    def volume_step(self) -> float:
        return 1 / HtdConstants.MAX_VOLUME

    async def async_volume_up(self) -> None:
        await self.client.async_volume_up(self.zone)

    async def async_volume_down(self) -> None:
        await self.client.async_volume_down(self.zone)

    async def async_turn_on(self):
        _LOGGER.debug("Attempting to turn on zone %d for device %s", self.zone, self.device_name)
        try:
            await self.client.async_power_on(self.zone)
            _LOGGER.debug("Successfully called async_power_on for zone %d", self.zone)
        except Exception as e:
            _LOGGER.error("Error turning on zone %d: %s", self.zone, e)
            _LOGGER.exception(e)


    async def async_turn_off(self):
        _LOGGER.debug("Attempting to turn off zone %d for device %s", self.zone, self.device_name)
        try:
            await self.client.async_power_off(self.zone)
            _LOGGER.debug("Successfully called async_power_off for zone %d", self.zone)
        except Exception as e:
            _LOGGER.error("Error turning off zone %d: %s", self.zone, e)
            _LOGGER.exception(e)

    @property
    def volume_level(self) -> float | None:
        return self._attr_volume_level


    @property
    def available(self) -> bool:
        return self.client.ready and self.zone_info is not None

    async def async_set_volume_level(self, volume: float):
        converted_volume = int(volume * HtdConstants.MAX_VOLUME)
        _LOGGER.info("setting new volume for zone %d to %f, raw htd = %d" % (self.zone, volume, converted_volume))
        await self.client.async_set_volume(self.zone, converted_volume)

    @property
    def is_volume_muted(self) -> bool | None:
        return self._attr_is_volume_muted

    async def async_mute_volume(self, mute):
        _LOGGER.debug("Attempting to set mute state to %s for zone %d", mute, self.zone)
        try:
            if mute:
                await self.client.async_mute(self.zone)
            else:
                await self.client.async_unmute(self.zone)
            _LOGGER.debug("Successfully set mute state to %s for zone %d", mute, self.zone)
        except Exception as e:
            _LOGGER.error("Error setting mute state for zone %d: %s", self.zone, e)
            _LOGGER.exception(e)


    @property
    def source(self) -> str | None:
        return self._attr_source

    @property
    def source_list(self):
        return self.sources

    @property
    def media_title(self):
        return self.source

    async def async_select_source(self, source: str):
        source_index = self.sources.index(source)
        await self.client.async_set_source(self.zone, source_index + 1)

    async def async_media_play(self):
        await self.async_turn_on()

    async def async_media_pause(self):
        await self.async_turn_off()

    async def async_media_stop(self):
        await self.async_turn_off()


    @property
    def icon(self):
        return "mdi:disc-player"

    @property
    def device_class(self) -> MediaPlayerDeviceClass:
        return MediaPlayerDeviceClass.RECEIVER

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        # Sensors should also register callbacks to HA when their state changes
        # print('registering callback')
        await self.client.async_subscribe(self._do_update)
        self.client.refresh()

    async def async_will_remove_from_hass(self):
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        await self.client.async_unsubscribe(self._do_update)

    def _update_properties(self) -> None:
        """Update entity attributes from the latest zone information."""
        if self.zone_info is None:
            self._attr_volume_level = None
            self._attr_is_volume_muted = None
            self._attr_source = None
            return

        self._attr_volume_level = (
            self.zone_info.volume / HtdConstants.MAX_VOLUME
        )
        self._attr_is_volume_muted = self.zone_info.mute
        try:
            self._attr_source = self.sources[self.zone_info.source - 1]
        except (IndexError, TypeError):
            self._attr_source = None

    def _do_update(self, zone: int):
        # If a specific zone is provided and it's not this entity's zone, ignore.
        # Zone 0 typically indicates a global update, which we should process.
        if zone is not None and zone != 0 and zone != self.zone:
            return

        # If the client does not have data for this specific zone yet, do not proceed.
        if not self.client.has_zone_data(self.zone):
            return

        # If it's an MCA client and a volume target is set, defer the update for volume-related properties.
        if isinstance(self.client, HtdMcaClient) and self.client.has_volume_target(self.zone):
            return

        # Update this entity's zone information regardless of the update source (specific zone or global).
        self.zone_info = self.client.get_zone(self.zone)
        self._update_properties()
        self.schedule_update_ha_state(force_refresh=True)

