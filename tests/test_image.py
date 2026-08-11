"""The test for the Thermal Comfort image platform."""

from xml.etree import ElementTree

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermal_comfort.const import DOMAIN
from custom_components.thermal_comfort.image import (
    PSYCHROMETRIC_CHART,
    SVG_CONTENT_TYPE,
)
from homeassistant.components.command_line.const import DOMAIN as COMMAND_LINE_DOMAIN
from homeassistant.components.image import (
    DOMAIN as PLATFORM_DOMAIN,
    valid_image_content_type,
)
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_component import DATA_INSTANCES

from .const import ADVANCED_USER_INPUT

TEST_NAME = f"{PLATFORM_DOMAIN}.test_thermal_comfort_{PSYCHROMETRIC_CHART}"

TEMPERATURE_TEST_SENSOR = {
    SENSOR_DOMAIN: {
        "command": "echo 0",
        "name": "test_temperature_sensor",
        "value_template": "{{ 25.0 | float }}",
    },
}

HUMIDITY_TEST_SENSOR = {
    SENSOR_DOMAIN: {
        "command": "echo 0",
        "name": "test_humidity_sensor",
        "value_template": "{{ 50.0 | float }}",
    },
}

DEFAULT_TEST_IMAGE = [
    "domains, config",
    [
        (
            [(COMMAND_LINE_DOMAIN, 2), (DOMAIN, 1)],
            {
                COMMAND_LINE_DOMAIN: [
                    TEMPERATURE_TEST_SENSOR,
                    HUMIDITY_TEST_SENSOR,
                ],
                DOMAIN: {
                    PLATFORM_DOMAIN: {
                        "name": "test_thermal_comfort",
                        "temperature_sensor": "sensor.test_temperature_sensor",
                        "humidity_sensor": "sensor.test_humidity_sensor",
                        "unique_id": "unique_thermal_comfort_id",
                    },
                },
            },
        ),
    ],
]


async def get_chart(hass: HomeAssistant, entity_id: str = TEST_NAME) -> str:
    """Return the rendered chart of an image entity as a string."""
    entity = hass.data[DATA_INSTANCES][PLATFORM_DOMAIN].get_entity(entity_id)
    assert entity is not None
    image = await entity.async_image()
    assert image is not None
    return image.decode("utf-8")


def parse_svg(chart: str) -> ElementTree.Element:
    """Parse a chart, which also asserts that it is well formed xml.

    The chart is produced by the code under test, not read from anywhere, so
    the usual worries about parsing xml from an untrusted source do not apply.
    """
    return ElementTree.fromstring(chart)  # noqa: S314


@pytest.mark.parametrize(*DEFAULT_TEST_IMAGE)
async def test_config(hass, start_ha):
    """Test that yaml configuration creates the chart."""
    assert len(hass.states.async_all(PLATFORM_DOMAIN)) == 1
    assert hass.states.get(TEST_NAME) is not None


@pytest.mark.parametrize(*DEFAULT_TEST_IMAGE)
async def test_unique_id(hass, start_ha):
    """Test that the unique id is built from the device unique id."""
    registry = er.async_get(hass)
    entry = registry.async_get(TEST_NAME)
    assert entry is not None
    assert entry.unique_id == f"unique_thermal_comfort_id{PSYCHROMETRIC_CHART}"


@pytest.mark.parametrize(*DEFAULT_TEST_IMAGE)
async def test_content_type(hass, start_ha):
    """Test that the chart is served as an image Home Assistant accepts."""
    entity = hass.data[DATA_INSTANCES][PLATFORM_DOMAIN].get_entity(TEST_NAME)
    assert entity.content_type == SVG_CONTENT_TYPE
    assert valid_image_content_type(entity.content_type) == SVG_CONTENT_TYPE


@pytest.mark.parametrize(*DEFAULT_TEST_IMAGE)
async def test_chart_shows_the_current_state(hass, start_ha):
    """Test that the chart is rendered for the state of the source sensors."""
    chart = await get_chart(hass)
    assert parse_svg(chart) is not None
    assert "test_thermal_comfort" in chart
    assert "25.0 °C" in chart
    assert "50.0 %" in chart
    # 25 °C at 50 % relative humidity, see test_psychrometrics.
    assert "9.88 g/kg" in chart


@pytest.mark.parametrize(*DEFAULT_TEST_IMAGE)
async def test_chart_follows_the_source_sensors(hass, start_ha):
    """Test that a new source state is picked up and redrawn."""
    before = hass.states.get(TEST_NAME).state

    hass.states.async_set("sensor.test_temperature_sensor", "15.0")
    await hass.async_block_till_done()
    chart = await get_chart(hass)
    assert "15.0 °C" in chart
    assert "50.0 %" in chart

    hass.states.async_set("sensor.test_humidity_sensor", "25.0")
    await hass.async_block_till_done()
    chart = await get_chart(hass)
    assert "15.0 °C" in chart
    assert "25.0 %" in chart

    # The state of an image entity is the time it was last updated.
    assert hass.states.get(TEST_NAME).state != before


@pytest.mark.parametrize(*DEFAULT_TEST_IMAGE)
async def test_chart_converts_the_source_unit(hass, start_ha):
    """Test that a fahrenheit source ends up on the celsius chart."""
    hass.states.async_set(
        "sensor.test_temperature_sensor",
        "77.0",
        {"unit_of_measurement": "°F", "device_class": "temperature"},
    )
    await hass.async_block_till_done()
    assert "25.0 °C" in await get_chart(hass)


@pytest.mark.parametrize(*DEFAULT_TEST_IMAGE)
async def test_chart_ignores_unusable_source_states(hass, start_ha):
    """Test that the last good chart survives a broken source sensor."""
    for value in ("unknown", "unavailable", "not a number", "-300.0"):
        hass.states.async_set("sensor.test_temperature_sensor", value)
        await hass.async_block_till_done()
        assert "25.0 °C" in await get_chart(hass)

    for value in ("0", "101", "unavailable"):
        hass.states.async_set("sensor.test_humidity_sensor", value)
        await hass.async_block_till_done()
        assert "50.0 %" in await get_chart(hass)


@pytest.mark.parametrize(*DEFAULT_TEST_IMAGE)
async def test_chart_ignores_unsupported_temperature_unit(hass, start_ha):
    """Test that a source unit we can not convert does not break the chart."""
    for unit in (None, "lx", "%"):
        hass.states.async_set(
            "sensor.test_temperature_sensor", "30.0", {ATTR_UNIT_OF_MEASUREMENT: unit}
        )
        await hass.async_block_till_done()
        chart = await get_chart(hass)
        assert parse_svg(chart) is not None
        assert "25.0 °C" in chart


MISSING_SOURCES_TEST_IMAGE = [
    "domains, config",
    [
        (
            [(DOMAIN, 1)],
            {
                DOMAIN: {
                    PLATFORM_DOMAIN: {
                        "name": "test_thermal_comfort",
                        "temperature_sensor": "sensor.does_not_exist_yet",
                        "humidity_sensor": "sensor.does_not_exist_either",
                        "unique_id": "unique_thermal_comfort_id",
                    },
                },
            },
        ),
    ],
]


@pytest.mark.parametrize(*MISSING_SOURCES_TEST_IMAGE)
async def test_chart_without_sources(hass, start_ha):
    """Test that a chart is drawn while the sources have no state yet."""
    chart = await get_chart(hass)
    assert parse_svg(chart) is not None
    assert "Waiting for temperature and humidity" in chart
    # The saturation curve does not depend on the state, so it is always there.
    assert 'class="saturation"' in chart


@pytest.mark.parametrize(*MISSING_SOURCES_TEST_IMAGE)
async def test_chart_picks_up_late_sources(hass, start_ha):
    """Test that sources appearing after startup are drawn."""
    hass.states.async_set("sensor.does_not_exist_yet", "18.5")
    hass.states.async_set("sensor.does_not_exist_either", "42.0")
    await hass.async_block_till_done()

    chart = await get_chart(hass)
    assert "18.5 °C" in chart
    assert "42.0 %" in chart


async def test_config_entry(hass: HomeAssistant):
    """Test that a config entry creates the chart next to the sensors."""
    hass.states.async_set("sensor.test_temperature_sensor", "25.0")
    hass.states.async_set("sensor.test_humidity_sensor", "50.0")

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data=ADVANCED_USER_INPUT,
        entry_id="test",
        unique_id="unique_config_entry_id",
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = f"{PLATFORM_DOMAIN}.test_thermal_comfort_{PSYCHROMETRIC_CHART}"
    assert hass.states.get(entity_id) is not None

    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    assert entry.unique_id == f"unique_config_entry_id{PSYCHROMETRIC_CHART}"
    # The chart belongs to the same device as the sensors of the entry.
    sensor_entry = registry.async_get(
        f"{SENSOR_DOMAIN}.test_thermal_comfort_absolute_humidity"
    )
    assert sensor_entry is not None
    assert entry.device_id == sensor_entry.device_id

    assert "25.0 °C" in await get_chart(hass, entity_id)
