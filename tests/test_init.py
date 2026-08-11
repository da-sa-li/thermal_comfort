"""Test setup process."""
from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermal_comfort import (
    async_migrate_entry,
    async_setup_entry,
    async_unload_entry,
    async_update_options,
)
from custom_components.thermal_comfort.const import DOMAIN, PLATFORMS

from .const import ADVANCED_USER_INPUT


async def test_setup_update_unload_entry(hass):
    """Test entry setup and unload."""

    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    config_entry = MockConfigEntry(
        domain=DOMAIN, data=ADVANCED_USER_INPUT, entry_id="test", unique_id=None
    )
    # Register the entry without letting Home Assistant set it up for real. A real
    # setup would register a second update listener, and the unique_id update below
    # would then trigger an actual reload racing with our explicit unload.
    config_entry.add_to_hass(hass)

    with patch.object(hass.config_entries, "async_update_entry") as p:
        assert await async_setup_entry(hass, config_entry)
        assert p.called

    assert DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]

    # check user input is in config
    for key in ADVANCED_USER_INPUT:
        if key in hass.data[DOMAIN][config_entry.entry_id]:
            assert (
                hass.data[DOMAIN][config_entry.entry_id][key]
                == ADVANCED_USER_INPUT[key]
            )

    hass.config_entries.async_forward_entry_setups.assert_called_with(
        config_entry, PLATFORMS
    )

    # ToDo test hass.data[DOMAIN][config_entry.entry_id][UPDATE_LISTENER]

    hass.config_entries.async_reload = AsyncMock()
    assert await async_update_options(hass, config_entry) is None
    hass.config_entries.async_reload.assert_called_with(config_entry.entry_id)

    # Unload the entry and verify that the data has been removed
    assert await async_unload_entry(hass, config_entry)
    assert config_entry.entry_id not in hass.data[DOMAIN]


async def test_migrate_entry_v1_to_v2(hass):
    """Test that migrating a version 1 entry bumps it to version 2."""
    config_entry = MockConfigEntry(
        domain=DOMAIN, data=ADVANCED_USER_INPUT, entry_id="test_migrate", version=1
    )
    config_entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, config_entry)
    assert config_entry.version == 2
