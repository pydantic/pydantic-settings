from __future__ import annotations as _annotations

import json
import sys
from pathlib import Path
from typing import Optional

import pytest
from pydantic import AnyHttpUrl, Field

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

try:
    import tomli  # type: ignore
except Exception:
    tomli = None

from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
    YamlConfigSettingsSource,
)


def test_init_kwargs_override_env_for_alias_with_populate_by_name(monkeypatch):
    class Settings(BaseSettings):
        abc: AnyHttpUrl = Field(validation_alias='my_abc')
        model_config = SettingsConfigDict(populate_by_name=True, extra='allow')

    monkeypatch.setenv('MY_ABC', 'http://localhost.com/')

    # Passing by field name should be accepted (populate_by_name=True) and should
    # override env-derived value. Also ensures init > env precedence with validation_alias.
    assert str(Settings(abc='http://prod.localhost.com/').abc) == 'http://prod.localhost.com/'


def test_deep_merge_multiple_file_json(tmp_path: Path):
    p1 = tmp_path / 'a.json'
    p2 = tmp_path / 'b.json'

    with open(p1, 'w') as f1:
        json.dump({'a': 1, 'nested': {'x': 1, 'y': 1}}, f1)
    with open(p2, 'w') as f2:
        json.dump({'b': 2, 'nested': {'y': 2, 'z': 3}}, f2)

    class Settings(BaseSettings):
        a: Optional[int] = None
        b: Optional[int] = None
        nested: dict[str, int]

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (JsonConfigSettingsSource(settings_cls, json_file=[p1, p2]),)

    s = Settings()
    assert s.a == 1
    assert s.b == 2
    assert s.nested == {'x': 1, 'y': 2, 'z': 3}


@pytest.mark.skipif(yaml is None, reason='pyYAML is not installed')
def test_deep_merge_multiple_file_yaml(tmp_path: Path):
    p1 = tmp_path / 'a.yaml'
    p2 = tmp_path / 'b.yaml'

    p1.write_text(
        """
    a: 1
    nested:
      x: 1
      y: 1
    """
    )
    p2.write_text(
        """
    b: 2
    nested:
      y: 2
      z: 3
    """
    )

    class Settings(BaseSettings):
        a: Optional[int] = None
        b: Optional[int] = None
        nested: dict[str, int]

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls, yaml_file=[p1, p2]),)

    s = Settings()
    assert s.a == 1
    assert s.b == 2
    assert s.nested == {'x': 1, 'y': 2, 'z': 3}


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_deep_merge_multiple_file_toml(tmp_path: Path):
    p1 = tmp_path / 'a.toml'
    p2 = tmp_path / 'b.toml'

    p1.write_text(
        """
    a=1

    [nested]
    x=1
    y=1
    """
    )
    p2.write_text(
        """
    b=2

    [nested]
    y=2
    z=3
    """
    )

    class Settings(BaseSettings):
        a: Optional[int] = None
        b: Optional[int] = None
        nested: dict[str, int]

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (TomlConfigSettingsSource(settings_cls, toml_file=[p1, p2]),)

    s = Settings()
    assert s.a == 1
    assert s.b == 2
    assert s.nested == {'x': 1, 'y': 2, 'z': 3}


@pytest.mark.skipif(yaml is None, reason='pyYAML is not installed')
def test_yaml_config_section_after_deep_merge(tmp_path: Path):
    # Ensure that config section is picked from the deep-merged data
    p1 = tmp_path / 'a.yaml'
    p2 = tmp_path / 'b.yaml'
    p1.write_text(
        """
    nested:
      x: 1
      y: 1
    """
    )
    p2.write_text(
        """
    nested:
      y: 2
      z: 3
    other: true
    """
    )

    class S2(BaseSettings):
        x: int
        y: int
        z: int
        model_config = SettingsConfigDict(yaml_config_section='nested')

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls, yaml_file=[p1, p2]),)

    s2 = S2()
    assert s2.model_dump() == {'x': 1, 'y': 2, 'z': 3}
