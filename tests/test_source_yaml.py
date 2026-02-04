"""
Test pydantic_settings.YamlConfigSettingsSource.
"""

from pathlib import Path

import pytest
from pydantic import BaseModel

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

try:
    import yaml
except ImportError:
    yaml = None


def test_repr() -> None:
    source = YamlConfigSettingsSource(BaseSettings, Path('config.yaml'))
    assert repr(source) == 'YamlConfigSettingsSource(yaml_file=config.yaml)'


@pytest.mark.skipif(yaml, reason='PyYAML is installed')
def test_yaml_not_installed(tmp_path):
    p = tmp_path / '.env'
    p.write_text(
        """
    foobar: "Hello"
    """
    )

    class Settings(BaseSettings):
        foobar: str
        model_config = SettingsConfigDict(yaml_file=p)

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls),)

    with pytest.raises(ImportError, match=r'^PyYAML is not installed, run `pip install pydantic-settings\[yaml\]`$'):
        Settings()


@pytest.mark.skipif(yaml is None, reason='pyYaml is not installed')
def test_yaml_file(tmp_path):
    p = tmp_path / '.env'
    p.write_text(
        """
    foobar: "Hello"
    null_field:
    nested:
        nested_field: "world!"
    """
    )

    class Nested(BaseModel):
        nested_field: str

    class Settings(BaseSettings):
        foobar: str
        nested: Nested
        null_field: str | None
        model_config = SettingsConfigDict(yaml_file=p)

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.foobar == 'Hello'
    assert s.nested.nested_field == 'world!'


@pytest.mark.skipif(yaml is None, reason='pyYaml is not installed')
def test_yaml_no_file():
    class Settings(BaseSettings):
        model_config = SettingsConfigDict(yaml_file=None)

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {}


@pytest.mark.skipif(yaml is None, reason='pyYaml is not installed')
def test_yaml_empty_file(tmp_path):
    p = tmp_path / '.env'
    p.write_text('')

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(yaml_file=p)

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {}


@pytest.mark.skipif(yaml is None, reason='pyYAML is not installed')
def test_multiple_file_yaml(tmp_path):
    p3 = tmp_path / '.env.yaml3'
    p4 = tmp_path / '.env.yaml4'
    p3.write_text(
        """
    yaml3: 3
    """
    )
    p4.write_text(
        """
    yaml4: 4
    """
    )

    class Settings(BaseSettings):
        yaml3: int
        yaml4: int

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls, yaml_file=[p3, p4]),)

    s = Settings()
    assert s.model_dump() == {'yaml3': 3, 'yaml4': 4}


@pytest.mark.skipif(yaml is None, reason='pyYAML is not installed')
@pytest.mark.parametrize('deep_merge', [False, True])
def test_multiple_file_yaml_deep_merge(tmp_path, deep_merge):
    p3 = tmp_path / '.env.yaml3'
    p4 = tmp_path / '.env.yaml4'
    p3.write_text(
        """
    hello: world

    nested:
      foo: 1
      bar: 2
    """
    )
    p4.write_text(
        """
    nested:
      foo: 3
    """
    )

    class Nested(BaseModel):
        foo: int
        bar: int = 0

    class Settings(BaseSettings):
        hello: str
        nested: Nested

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls, yaml_file=[p3, p4], deep_merge=deep_merge),)

    s = Settings()
    assert s.model_dump() == {'hello': 'world', 'nested': {'foo': 3, 'bar': 2 if deep_merge else 0}}


@pytest.mark.skipif(yaml is None, reason='pyYAML is not installed')
def test_yaml_config_section(tmp_path):
    p = tmp_path / '.env'
    p.write_text(
        """
    foobar: "Hello"
    nested:
        nested_field: "world!"
    """
    )

    class Settings(BaseSettings):
        nested_field: str

        model_config = SettingsConfigDict(yaml_file=p, yaml_config_section='nested')

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.nested_field == 'world!'


@pytest.mark.skipif(yaml is None, reason='pyYAML is not installed')
def test_invalid_yaml_config_section(tmp_path):
    p = tmp_path / '.env'
    p.write_text(
        """
    foobar: "Hello"
    nested:
        nested_field: "world!"
    """
    )

    class Settings(BaseSettings):
        nested_field: str

        model_config = SettingsConfigDict(yaml_file=p, yaml_config_section='invalid_key')

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls),)

    with pytest.raises(KeyError, match='yaml_config_section key "invalid_key" not found in .+'):
        Settings()


@pytest.mark.skipif(yaml is None, reason='pyYAML is not installed')
def test_yaml_config_section_nested_path(tmp_path):
    p = tmp_path / 'config.yaml'
    p.write_text(
        """
    config:
      app:
        settings:
          database_url: "postgresql://localhost/db"
          api_key: "secret123"
      logging:
        level: "INFO"
    """
    )

    class Settings(BaseSettings):
        database_url: str
        api_key: str

        model_config = SettingsConfigDict(yaml_file=p, yaml_config_section='config.app.settings')

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.database_url == 'postgresql://localhost/db'
    assert s.api_key == 'secret123'


@pytest.mark.skipif(yaml is None, reason='pyYAML is not installed')
def test_yaml_config_section_nested_path_two_levels(tmp_path):
    p = tmp_path / 'config.yaml'
    p.write_text(
        """
    app:
      settings:
        host: "localhost"
        port: 8000
    """
    )

    class Settings(BaseSettings):
        host: str
        port: int

        model_config = SettingsConfigDict(yaml_file=p, yaml_config_section='app.settings')

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.host == 'localhost'
    assert s.port == 8000


@pytest.mark.skipif(yaml is None, reason='pyYAML is not installed')
def test_invalid_yaml_config_section_nested_path(tmp_path):
    p = tmp_path / 'config.yaml'
    p.write_text(
        """
    config:
      app:
        settings:
          database_url: "postgresql://localhost/db"
    """
    )

    class Settings(BaseSettings):
        database_url: str

        model_config = SettingsConfigDict(yaml_file=p, yaml_config_section='config.app.invalid')

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls),)

    with pytest.raises(KeyError, match='yaml_config_section key "config.app.invalid" not found in .+'):
        Settings()
