from argparse import Namespace

import pytest
from pydantic import BaseModel

from pydantic_settings import BaseSettings, CliSettingsSource, CliSubCommand, SettingsError


class Value(BaseModel):
    value: int = 0


class Empty(BaseModel):
    pass


@pytest.mark.parametrize('case_sensitive', [False, True])
def test_default_subcommand_ignores_unrelated_destination(case_sensitive: bool) -> None:
    class Settings(BaseSettings):
        prerun: Value = Value()
        run: CliSubCommand[Value]

    settings = Settings(
        _case_sensitive=case_sensitive,
        _cli_parse_args=['--prerun.value', '1', 'run'],
        _cli_exit_on_error=False,
    )

    assert settings.prerun == Value(value=1)
    assert settings.run == Value()


def test_empty_subcommand_ignores_unrelated_destination() -> None:
    class Settings(BaseSettings):
        prerun: Value = Value()
        run: CliSubCommand[Empty]

    settings = Settings(_cli_parse_args=['--prerun.value=1', 'run'], _cli_exit_on_error=False)

    assert settings.prerun == Value(value=1)
    assert settings.run == Empty()


@pytest.mark.parametrize('command_first', [False, True])
def test_external_parse_destination_order_does_not_hide_selected_command(command_first: bool) -> None:
    class Settings(BaseSettings):
        prerun: Value = Value()
        run: CliSubCommand[Value]

    items = [('prerun.value', '1'), (':subcommand', 'run')]
    parsed_args = dict(reversed(items) if command_first else items)
    source = CliSettingsSource(Settings)(parsed_args=Namespace(**parsed_args))
    settings = Settings(_cli_settings_source=source)

    assert settings.prerun == Value(value=1)
    assert settings.run == Value()


def test_populated_subcommand_keeps_its_fields() -> None:
    class Settings(BaseSettings):
        prerun: Value = Value()
        run: CliSubCommand[Value]

    settings = Settings(_cli_parse_args=['--prerun.value=1', 'run', '--value=2'], _cli_exit_on_error=False)

    assert settings.prerun == Value(value=1)
    assert settings.run == Value(value=2)


def test_root_option_after_subcommand_is_still_rejected() -> None:
    class Settings(BaseSettings):
        prerun: Value = Value()
        run: CliSubCommand[Value]

    with pytest.raises(SettingsError, match=r'unrecognized arguments: --prerun\.value=1'):
        Settings(_cli_parse_args=['run', '--prerun.value=1'], _cli_exit_on_error=False)
