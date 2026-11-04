import json

import pytest

from pydantic_settings import BaseSettings, CliApp, SettingsError


@pytest.mark.parametrize('value', ['a"b', 'a\\b', 'first\nsecond', '\tvalue', 'caf\u00e9', '\U0001f98a'])
@pytest.mark.parametrize('roundtrip', [False, True])
def test_cli_json_list_string_escapes(value, roundtrip):
    class Settings(BaseSettings):
        values: list[str]

    values = [value, 'plain']
    args = CliApp.serialize(Settings(values=values)) if roundtrip else ['--values', json.dumps(values)]
    assert Settings(_cli_parse_args=args).values == values


@pytest.mark.parametrize('style', ['repeated', 'lazy', 'json'])
def test_cli_list_path_controls(style):
    class Settings(BaseSettings):
        values: list[str]

    values = [r'C:\work\file.txt', 'plain']
    args = {
        'repeated': ['--values', values[0], '--values', values[1]],
        'lazy': ['--values', ','.join(values)],
        'json': ['--values', json.dumps(values)],
    }[style]
    assert Settings(_cli_parse_args=args).values == values


@pytest.mark.parametrize('value', ['["first" "second"]', '["first"suffix]'])
def test_cli_quoted_list_values_require_a_separator(value):
    class Settings(BaseSettings):
        values: list[str]

    with pytest.raises(SettingsError):
        Settings(_cli_parse_args=['--values', value])
