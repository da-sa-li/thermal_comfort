"""Image platform for thermal_comfort.

Renders a psychrometric chart of the air state a thermal comfort device is
watching. The chart is an SVG document served through the Home Assistant image
proxy, so no additional python dependencies and no frontend resources are
needed to look at it.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_UNIQUE_ID
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import DEFAULT_NAME, DOMAIN
from .psychrometrics import render_psychrometric_chart
from .sensor import (
    CONF_HUMIDITY_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    humidity_from_state,
    id_generator,
    temperature_from_state,
)

_LOGGER = logging.getLogger(__name__)

PSYCHROMETRIC_CHART = "psychrometric_chart"

SVG_CONTENT_TYPE = "image/svg+xml"

IMAGE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_NAME): cv.string,
        vol.Required(CONF_TEMPERATURE_SENSOR): cv.entity_id,
        vol.Required(CONF_HUMIDITY_SENSOR): cv.entity_id,
        vol.Required(CONF_UNIQUE_ID): cv.string,
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the Thermal Comfort images from yaml configuration."""
    if discovery_info is None:
        return False

    async_add_entities(
        [
            PsychrometricChart(
                hass=hass,
                name=device_config.get(CONF_NAME),
                unique_id=device_config.get(CONF_UNIQUE_ID),
                temperature_entity=device_config.get(CONF_TEMPERATURE_SENSOR),
                humidity_entity=device_config.get(CONF_HUMIDITY_SENSOR),
                is_config_entry=False,
            )
            for device_config in discovery_info["devices"]
        ]
    )
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the image configured via user interface.

    Called via async_forward_entry_setups(, IMAGE) from __init__.py
    """
    data = hass.data[DOMAIN][config_entry.entry_id]
    _LOGGER.debug("async_setup_entry: %s", data)

    async_add_entities(
        [
            PsychrometricChart(
                hass=hass,
                name=data[CONF_NAME],
                unique_id=f"{config_entry.unique_id}",
                temperature_entity=data[CONF_TEMPERATURE_SENSOR],
                humidity_entity=data[CONF_HUMIDITY_SENSOR],
            )
        ]
    )


class PsychrometricChart(ImageEntity):
    """Psychrometric chart of the air a thermal comfort device is watching."""

    _attr_content_type = SVG_CONTENT_TYPE

    def __init__(
        self,
        hass: HomeAssistant,
        name: str | None,
        unique_id: str,
        temperature_entity: str,
        humidity_entity: str,
        is_config_entry: bool = True,
    ) -> None:
        """Initialize the psychrometric chart."""
        super().__init__(hass)
        self._temperature_entity = temperature_entity
        self._humidity_entity = humidity_entity
        self._temperature: float | None = None
        self._humidity: float | None = None
        self._chart: bytes | None = None
        self._title = name

        entity_description = {
            "key": PSYCHROMETRIC_CHART,
            "translation_key": PSYCHROMETRIC_CHART,
            "has_entity_name": True,
            "icon": "mdi:chart-scatter-plot",
        }
        if not is_config_entry and name is not None:
            # Yaml sensors keep the device name as part of the entity name.
            entity_description["has_entity_name"] = False
            entity_description["name"] = f"{name} Psychrometric chart"
        self.entity_description = ImageEntityDescription(**entity_description)

        self._attr_unique_id = id_generator(unique_id, PSYCHROMETRIC_CHART)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_id)},
            name=name,
            manufacturer=DEFAULT_NAME,
            model="Virtual Device",
        )

    async def async_added_to_hass(self) -> None:
        """Register callbacks and pick up the current state of the sources."""
        await super().async_added_to_hass()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._temperature_entity, self._async_temperature_changed
            )
        )
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._humidity_entity, self._async_humidity_changed
            )
        )

        if (
            reading := temperature_from_state(
                self.hass, self.hass.states.get(self._temperature_entity)
            )
        ) is not None:
            self._temperature = reading.celsius
        self._humidity = humidity_from_state(
            self.hass.states.get(self._humidity_entity)
        )
        self._async_chart_changed()

    @callback
    def _async_temperature_changed(self, event) -> None:
        """Handle temperature source state changes."""
        state = event.data.get("new_state")
        if (reading := temperature_from_state(self.hass, state)) is None:
            _LOGGER.info(
                "Temperature has an invalid value: %s. Can't update the chart.", state
            )
            return
        if reading.celsius != self._temperature:
            self._temperature = reading.celsius
            self._async_chart_changed()

    @callback
    def _async_humidity_changed(self, event) -> None:
        """Handle humidity source state changes."""
        state = event.data.get("new_state")
        if (humidity := humidity_from_state(state)) is None:
            _LOGGER.info(
                "Relative humidity has an invalid value: %s. Can't update the chart.",
                state,
            )
            return
        if humidity != self._humidity:
            self._humidity = humidity
            self._async_chart_changed()

    @callback
    def _async_chart_changed(self) -> None:
        """Drop the rendered chart and tell the frontend a new one is available."""
        self._chart = None
        self._attr_image_last_updated = dt_util.utcnow()
        self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        """Return the psychrometric chart as an SVG document.

        Rendering happens on demand and is cached until one of the sources
        changes, so sensor updates stay cheap while nobody looks at the chart.
        """
        if self._chart is None:
            self._chart = render_psychrometric_chart(
                self._temperature, self._humidity, title=self._title
            ).encode("utf-8")
        return self._chart
