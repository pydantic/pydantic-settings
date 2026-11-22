import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic.fields import FieldInfo

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
from pydantic_settings.sources import PydanticBaseEnvSettingsSource


@pytest.mark.parametrize('port', ['8000', 'invalid'])
def test_source_with_only_call(tmp_path: Path, port: str):
    config_file = tmp_path / 'settings.json'
    config_file.write_text(json.dumps({'port': port, 'numbers': [1, 2]}))

    class FileSource(PydanticBaseSettingsSource):
        def __call__(self) -> dict[str, Any]:
            return json.loads(config_file.read_text())

    class Settings(BaseSettings):
        port: int
        numbers: list[int]

        @classmethod
        def settings_customise_sources(cls, settings_cls, init_settings, **kwargs):
            return init_settings, FileSource(settings_cls)

    if port == 'invalid':
        with pytest.raises(ValidationError, match='port'):
            Settings()
    else:
        assert Settings().model_dump() == {'port': 8000, 'numbers': [1, 2]}

    assert Settings(port=9000).model_dump() == {'port': 9000, 'numbers': [1, 2]}


def test_source_can_keep_using_field_helpers():
    class Source(PydanticBaseSettingsSource):
        def __call__(self) -> dict[str, Any]:
            field = self.settings_cls.model_fields['numbers']
            return {'numbers': self.prepare_field_value('numbers', field, '[1, 2]', False)}

    class Settings(BaseSettings):
        numbers: list[int]

        @classmethod
        def settings_customise_sources(cls, settings_cls, **kwargs):
            return (Source(settings_cls),)

    assert Settings().numbers == [1, 2]


def test_unimplemented_field_lookup():
    class Source(PydanticBaseSettingsSource):
        def __call__(self) -> dict[str, Any]:
            return {}

    class Settings(BaseSettings):
        value: int = 1

    with pytest.raises(NotImplementedError):
        Source(Settings).get_field_value(Settings.model_fields['value'], 'value')


def test_source_still_requires_call():
    class Source(PydanticBaseSettingsSource):
        def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
            return None, field_name, False

    with pytest.raises(TypeError, match='__call__'):
        Source(BaseSettings)


def test_env_source_still_requires_field_lookup():
    class Source(PydanticBaseEnvSettingsSource):
        def __call__(self) -> dict[str, Any]:
            return {}

    with pytest.raises(TypeError, match='get_field_value'):
        Source(BaseSettings)


def test_custom_env_source_field_lookup():
    class Source(PydanticBaseEnvSettingsSource):
        def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
            return '[1, 2]', field_name, False

    class Settings(BaseSettings):
        numbers: list[int]

        @classmethod
        def settings_customise_sources(cls, settings_cls, **kwargs):
            return (Source(settings_cls),)

    assert Settings().numbers == [1, 2]
