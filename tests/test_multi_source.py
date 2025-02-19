"""
Integration tests with multiple sources
"""

from typing import Tuple, Type, Union

from pydantic import BaseModel, ValidationError
import pytest

from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

def test_line_errors_from_source(monkeypatch, tmp_path):
    monkeypatch.setenv("SETTINGS_NESTED__NESTED_FIELD", "a")
    p = tmp_path / 'settings.json'
    p.write_text(
        """
    {"foobar": 0, "null_field": null}
    """
    )

    class Nested(BaseModel):
        nested_field: int

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(
            json_file=p,
            env_prefix="SETTINGS_",
            env_nested_delimiter="__",
            validate_each_source=True
        )
        foobar: str
        nested: Nested
        null_field: Union[str, None]
        extra: bool

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (
                JsonConfigSettingsSource(settings_cls),
                env_settings,
                init_settings
            )

    with pytest.raises(ValidationError) as exc_info:
        _ = Settings(null_field=0)

    assert exc_info.value.errors(include_url=False) == [
        {
            'input': 0,
            'loc': ('JsonConfigSettingsSource', 'foobar',),
            'msg': 'Input should be a valid string',
            'type': 'string_type',
        },
        {
            'input': 'a',
            'loc': ('EnvSettingsSource', 'nested', 'nested_field'),
            'msg': 'Input should be a valid integer, unable to parse string as an integer',
            'type': 'int_parsing'
        },
        {
            'input': 0,
            'loc': ('InitSettingsSource', 'null_field',),
            'msg': 'Input should be a valid string',
            'type': 'string_type'
        },
        {
            'input': {'foobar': 0, 'nested': {'nested_field': 'a'}, 'null_field': None},
            'loc': ('extra',),
            'msg': 'Field required',
            'type': 'missing'
        }
    ]
