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


@pytest.mark.skipif(yaml is None, reason='pyYAML is not installed')
def test_yaml_config_section_with_literal_dots(tmp_path):
    """Test that keys containing literal dots can be accessed using greedy matching."""
    p = tmp_path / 'config.yaml'
    p.write_text(
        """
    "app.settings":
      database_url: "postgresql://localhost/db"
      api_key: "secret123"
    config:
      "server.prod":
        host: "prod.example.com"
        port: 443
    """
    )

    # Test accessing a top-level key with literal dots
    class Settings1(BaseSettings):
        database_url: str
        api_key: str

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

    s1 = Settings1()
    assert s1.database_url == 'postgresql://localhost/db'
    assert s1.api_key == 'secret123'

    # Test accessing a nested key where the child has literal dots
    class Settings2(BaseSettings):
        host: str
        port: int

        model_config = SettingsConfigDict(yaml_file=p, yaml_config_section='config.server.prod')

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

    s2 = Settings2()
    assert s2.host == 'prod.example.com'
    assert s2.port == 443


@pytest.mark.skipif(yaml is None, reason='pyYAML is not installed')
def test_yaml_config_section_empty_path(tmp_path):
    """Test that empty section path is rejected."""
    p = tmp_path / 'config.yaml'
    p.write_text(
        """
    app:
      settings:
        host: "localhost"
    """
    )

    class Settings(BaseSettings):
        host: str
        model_config = SettingsConfigDict(yaml_file=p, yaml_config_section='')

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

    with pytest.raises(ValueError, match='yaml_config_section cannot be empty'):
        Settings()


@pytest.mark.skipif(yaml is None, reason='pyYAML is not installed')
def test_yaml_config_section_unusual_literal_keys(tmp_path):
    """Test that keys with leading/trailing/consecutive dots can be accessed as literal keys."""
    p = tmp_path / 'config.yaml'
    p.write_text(
        """
    ".leading":
      value: "has leading dot"
    "trailing.":
      value: "has trailing dot"
    "double..dots":
      value: "has consecutive dots"
    "":
      value: "empty key"
    """
    )

    # Test leading dot key
    class Settings1(BaseSettings):
        value: str
        model_config = SettingsConfigDict(yaml_file=p, yaml_config_section='.leading')

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

    s1 = Settings1()
    assert s1.value == 'has leading dot'

    # Test trailing dot key
    class Settings2(BaseSettings):
        value: str
        model_config = SettingsConfigDict(yaml_file=p, yaml_config_section='trailing.')

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

    s2 = Settings2()
    assert s2.value == 'has trailing dot'

    # Test consecutive dots key
    class Settings3(BaseSettings):
        value: str
        model_config = SettingsConfigDict(yaml_file=p, yaml_config_section='double..dots')

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

    s3 = Settings3()
    assert s3.value == 'has consecutive dots'


@pytest.mark.skipif(yaml is None, reason='pyYAML is not installed')
def test_yaml_config_section_complex_unusual_keys(tmp_path):
    """Test complex scenario with multiple unusual characters in nested keys."""
    p = tmp_path / 'config.yaml'
    p.write_text(
        """
    "..leading..double.trailing..":
      "value..double":
        normal: "regular value"
        number: 42
    """
    )

    # Test accessing deeply nested path with unusual keys at each level
    # Path: "..leading..double.trailing.." (literal key) -> "value..double" (literal key)
    class Settings(BaseSettings):
        normal: str
        number: int

        model_config = SettingsConfigDict(
            yaml_file=p, yaml_config_section='..leading..double.trailing...value..double'
        )

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
    assert s.normal == 'regular value'
    assert s.number == 42


@pytest.mark.skipif(yaml is None, reason='pyYAML is not installed')
def test_yaml_config_section_non_dict_intermediate(tmp_path):
    """Test that traversing through non-dict intermediate values raises clear error."""
    p = tmp_path / 'config.yaml'
    p.write_text(
        """
    app:
      name: "MyApp"
      settings:
        host: "localhost"
    """
    )

    # Try to traverse through a string value (app.name.something)
    class Settings(BaseSettings):
        host: str
        model_config = SettingsConfigDict(yaml_file=p, yaml_config_section='app.name.host')

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

    with pytest.raises(TypeError, match='yaml_config_section path.*cannot be traversed.*not a dictionary'):
        Settings()
