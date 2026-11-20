import json

import pytest
from pydantic import AliasChoices, Field

from pydantic_settings import (
    BaseSettings,
    InitSettingsSource,
    JsonConfigSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
    YamlConfigSettingsSource,
)


@pytest.mark.parametrize('source_type', ['init', 'json', 'toml', 'yaml'])
@pytest.mark.parametrize('case_sensitive', [False, True])
@pytest.mark.parametrize(
    'values, expected',
    [
        ({'TIMEOUT': 30}, (30, 30)),
        ({'READ_TIMEOUT': 10, 'TIMEOUT': 30}, (10, 30)),
        ({'WRITE_TIMEOUT': 20, 'TIMEOUT': 30}, (30, 20)),
        ({'READ_TIMEOUT': 10, 'WRITE_TIMEOUT': 20, 'TIMEOUT': 30}, (10, 20)),
    ],
)
def test_shared_alias_choices(tmp_path, source_type, case_sensitive, values, expected):
    class Settings(BaseSettings):
        model_config = SettingsConfigDict(case_sensitive=case_sensitive)
        read_timeout: int = Field(validation_alias=AliasChoices('READ_TIMEOUT', 'TIMEOUT'))
        write_timeout: int = Field(validation_alias=AliasChoices('WRITE_TIMEOUT', 'TIMEOUT'))

        @classmethod
        def settings_customise_sources(cls, settings_cls, **kwargs):
            if source_type == 'init':
                return (InitSettingsSource(settings_cls, values),)
            path = tmp_path / f'config.{source_type}'
            if source_type == 'json':
                path.write_text(json.dumps(values))
                return (JsonConfigSettingsSource(settings_cls, json_file=path),)
            if source_type == 'toml':
                path.write_text('\n'.join(f'{key} = {value}' for key, value in values.items()))
                return (TomlConfigSettingsSource(settings_cls, toml_file=path),)
            pytest.importorskip('yaml')
            path.write_text('\n'.join(f'{key}: {value}' for key, value in values.items()))
            return (YamlConfigSettingsSource(settings_cls, yaml_file=path),)

    settings = Settings()
    assert (settings.read_timeout, settings.write_timeout) == expected


@pytest.mark.parametrize('reverse_fields', [False, True])
def test_shared_alias_choices_defaults_and_case_insensitive_input(reverse_fields):
    class Settings(BaseSettings):
        read_timeout: int = Field(1, validation_alias=AliasChoices('READ_TIMEOUT', 'TIMEOUT'))
        write_timeout: int = Field(2, validation_alias=AliasChoices('WRITE_TIMEOUT', 'TIMEOUT'))

    if reverse_fields:
        Settings.model_fields = dict(reversed(Settings.model_fields.items()))
        Settings.model_rebuild(force=True)

    values = {'timeout': 30}
    source = InitSettingsSource(Settings, values)
    assert source() == {'READ_TIMEOUT': 30, 'WRITE_TIMEOUT': 30}
    assert values == {'timeout': 30}
    settings = Settings.model_validate(source())
    assert (settings.read_timeout, settings.write_timeout) == (30, 30)


def test_shared_alias_choices_preserves_extras():
    class Settings(BaseSettings):
        model_config = SettingsConfigDict(extra='allow')
        read_timeout: int = Field(validation_alias=AliasChoices('READ_TIMEOUT', 'TIMEOUT'))
        write_timeout: int = Field(validation_alias=AliasChoices('WRITE_TIMEOUT', 'TIMEOUT'))

    values = {'READ_TIMEOUT': 10, 'TIMEOUT': 30, 'other': 40}
    source = InitSettingsSource(Settings, values)
    assert source() == {'READ_TIMEOUT': 10, 'WRITE_TIMEOUT': 30, 'other': 40}
    assert values == {'READ_TIMEOUT': 10, 'TIMEOUT': 30, 'other': 40}
