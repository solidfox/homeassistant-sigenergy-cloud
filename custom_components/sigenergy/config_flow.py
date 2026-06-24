"""Config flow for the Sigenergy integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from sigenergy_cloud import (
    SigenergyCloudAuthError,
    SigenergyCloudClient,
    SigenergyCloudError,
)

from .const import (
    CONF_ENABLED_MODULES,
    CONF_REGION,
    DEFAULT_ENABLED_MODULES,
    DOMAIN,
    LOGGER,
    REGIONS,
    enabled_modules_from_options,
)


def _modules_schema(default_modules: list[str]) -> vol.Schema:
    """Return the shared enabled-modules schema."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_ENABLED_MODULES,
                default=default_modules,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(DEFAULT_ENABLED_MODULES),
                    multiple=True,
                    translation_key=CONF_ENABLED_MODULES,
                )
            )
        }
    )


class SigenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sigenergy."""

    VERSION = 3

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return SigenOptionsFlowHandler(config_entry)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                station_id = await self._validate_and_get_station_id(user_input)
            except SigenergyCloudAuthError:
                errors["base"] = "auth"
            except SigenergyCloudError as exc:
                LOGGER.error("Sigenergy connection error: %s", exc)
                errors["base"] = "connection"
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Unexpected error: %s", exc)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(station_id)
                self._abort_if_unique_id_configured()
                config_data = {
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_REGION: user_input.get(CONF_REGION, "eu"),
                }
                options = {
                    CONF_ENABLED_MODULES: user_input.get(
                        CONF_ENABLED_MODULES, list(DEFAULT_ENABLED_MODULES)
                    )
                }
                return self.async_create_entry(
                    title=f"Sigenergy ({user_input[CONF_USERNAME]})",
                    data=config_data,
                    options=options,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=(user_input or {}).get(CONF_USERNAME, vol.UNDEFINED),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.EMAIL,
                        ),
                    ),
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        ),
                    ),
                    vol.Required(
                        CONF_REGION,
                        default=(user_input or {}).get(CONF_REGION, "eu"),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=REGIONS,
                            translation_key="region",
                        ),
                    ),
                    vol.Optional(
                        CONF_ENABLED_MODULES,
                        default=list(DEFAULT_ENABLED_MODULES),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(DEFAULT_ENABLED_MODULES),
                            multiple=True,
                            translation_key=CONF_ENABLED_MODULES,
                        )
                    ),
                },
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> config_entries.ConfigFlowResult:
        """Handle re-authentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Confirm re-authentication."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            new_data = {**reauth_entry.data, **user_input}
            try:
                await self._validate_and_get_station_id(new_data)
            except SigenergyCloudAuthError:
                errors["base"] = "auth"
            except SigenergyCloudError as exc:
                LOGGER.error("Sigenergy connection error: %s", exc)
                errors["base"] = "connection"
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Unexpected error: %s", exc)
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data=new_data,
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        ),
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "username": reauth_entry.data.get(CONF_USERNAME, ""),
            },
        )

    async def _validate_and_get_station_id(self, data: dict[str, Any]) -> str:
        """Create a client, authenticate, and return the station ID."""
        client = SigenergyCloudClient(
            username=data[CONF_USERNAME],
            password=data[CONF_PASSWORD],
            region=data.get(CONF_REGION, "eu"),
            session=async_get_clientsession(self.hass),
        )
        try:
            await client.connect()
            if client.station_id is None:
                msg = "Sigenergy Cloud did not return a station ID"
                raise SigenergyCloudError(msg)
            return str(client.station_id)
        finally:
            await client.close()


class SigenOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Sigenergy options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage optional cloud fetch modules."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        enabled_modules = enabled_modules_from_options(self.config_entry.options)
        default_modules = [
            module for module in DEFAULT_ENABLED_MODULES if module in enabled_modules
        ]
        return self.async_show_form(
            step_id="init",
            data_schema=_modules_schema(default_modules),
        )
