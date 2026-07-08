"""
Test pydantic_settings.TomlConfigSettingsSource.
"""

import importlib
import sys
import zipfile
from importlib.resources import files
from pathlib import Path

import pytest
from pydantic import BaseModel

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

try:
    import tomli
except ImportError:
    tomli = None


def test_repr() -> None:
    source = TomlConfigSettingsSource(BaseSettings, Path('config.toml'))
    assert repr(source) == 'TomlConfigSettingsSource(toml_file=config.toml, toml_table_header=())'


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_toml_file(tmp_path):
    p = tmp_path / '.env'
    p.write_text(
        """
    foobar = "Hello"

    [nested]
    nested_field = "world!"
    """
    )

    class Nested(BaseModel):
        nested_field: str

    class Settings(BaseSettings):
        foobar: str
        nested: Nested
        model_config = SettingsConfigDict(toml_file=p)

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (TomlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.foobar == 'Hello'
    assert s.nested.nested_field == 'world!'


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_toml_no_file():
    class Settings(BaseSettings):
        model_config = SettingsConfigDict(toml_file=None)

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (TomlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {}


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_toml_file_missing(tmp_path):
    p = tmp_path / 'does-not-exist.toml'

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(toml_file=p)

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (TomlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {}


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_multiple_file_toml(tmp_path):
    p1 = tmp_path / '.env.toml1'
    p2 = tmp_path / '.env.toml2'
    p1.write_text(
        """
    toml1=1
    """
    )
    p2.write_text(
        """
    toml2=2
    """
    )

    class Settings(BaseSettings):
        toml1: int
        toml2: int

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
    assert s.model_dump() == {'toml1': 1, 'toml2': 2}


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
@pytest.mark.parametrize('deep_merge', [False, True])
def test_multiple_file_toml_merge(tmp_path, deep_merge):
    p1 = tmp_path / '.env.toml1'
    p2 = tmp_path / '.env.toml2'
    p1.write_text(
        """
    hello = "world"

    [nested]
    foo=1
    bar=2
    """
    )
    p2.write_text(
        """
    [nested]
    foo=3
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
            return (TomlConfigSettingsSource(settings_cls, toml_file=[p1, p2], deep_merge=deep_merge),)

    s = Settings()
    assert s.model_dump() == {'hello': 'world', 'nested': {'foo': 3, 'bar': 2 if deep_merge else 0}}


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_toml_table_header(tmp_path):
    p = tmp_path / 'test.toml'
    p.write_text(
        """
    [app]
    hello = "world"
    """
    )

    class Settings(BaseSettings):
        hello: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (TomlConfigSettingsSource(settings_cls, toml_file=p, toml_table_header=('app',)),)

    s = Settings()
    assert s.model_dump() == {'hello': 'world'}


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_toml_table_header_from_model_config(tmp_path):
    p = tmp_path / 'test.toml'
    p.write_text(
        """
    [app]
    hello = "world"
    """
    )

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(toml_file=p, toml_table_header=('app',))

        hello: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (TomlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {'hello': 'world'}


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_toml_table_header_no_header(tmp_path):
    """If a toml file is read, but the configured table header is missing from the result, raise an error"""
    p = tmp_path / 'test.toml'
    p.write_text(
        """
    [other]
    hello = "world"
    """
    )

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(toml_file=p, toml_table_header=('app',))

        hello: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (TomlConfigSettingsSource(settings_cls),)

    with pytest.raises(KeyError, match='toml_table_header key "app" not found in .*'):
        Settings()


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_toml_table_header_no_file():
    """If a table header is configured, but the toml file is unset, no error should be raised."""

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(toml_file=None, toml_table_header=('app',))

        hello: str = 'world'

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (TomlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {'hello': 'world'}


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_toml_table_header_file_missing(tmp_path):
    """If a table header is configured, but the configured toml file is missing, no error should be raised."""
    p = tmp_path / 'does-not-exist.toml'

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(toml_file=p, toml_table_header=('app',))

        hello: str = 'world'

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (TomlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {'hello': 'world'}


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_toml_table_header_file_multiple(tmp_path):
    """If multiple files are configured and at least one is available, the table header extraction should work"""
    p1 = tmp_path / 'test.toml'
    p1.write_text(
        """
    [app]
    hello = "world"
    """
    )
    p2 = tmp_path / 'does-not-exist.toml'

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(toml_file=[p1, p2], toml_table_header=('app',))

        hello: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (TomlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {'hello': 'world'}


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_toml_table_header_file_multiple_no_header(tmp_path):
    """When multiple files are configured and at least one is available, if the configured table header is missing from the result, an error should be raised"""
    p1 = tmp_path / 'test.toml'
    p1.write_text(
        """
    [other]
    hello = "world"
    """
    )
    p2 = tmp_path / 'does-not-exist.toml'

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(toml_file=[p1, p2], toml_table_header=('app',))

        hello: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (TomlConfigSettingsSource(settings_cls),)

    with pytest.raises(KeyError, match='toml_table_header key "app" not found in .*'):
        Settings()


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_toml_table_header_file_multiple_no_files(tmp_path):
    """When multiple files are configured but none are available, if the configured table header is missing from the result, no error should be raised"""
    p1 = tmp_path / 'does-not-exist.toml'
    p2 = tmp_path / 'also-does-not-exist.toml'

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(toml_file=[p1, p2], toml_table_header=('app',))

        hello: str = 'world'

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (TomlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {'hello': 'world'}


@pytest.fixture
def zip_traversable(tmp_path):
    """Factory returning a genuine non-Path ``Traversable`` pointing at a resource inside a zip/wheel."""
    created: list[str] = []

    def _make(pkg_name: str, filename: str, content: str):
        zip_path = tmp_path / f'{pkg_name}.zip'
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr(f'{pkg_name}/__init__.py', '')
            zf.writestr(f'{pkg_name}/{filename}', content)
        sys.path.insert(0, str(zip_path))
        importlib.invalidate_caches()
        created.append(pkg_name)
        trav = files(pkg_name).joinpath(filename)
        # Sanity check: a zip-packaged resource is not a filesystem ``Path``.
        assert not isinstance(trav, Path)
        return trav

    yield _make

    for pkg_name in created:
        sys.modules.pop(pkg_name, None)
        zip_str = str(tmp_path / f'{pkg_name}.zip')
        if zip_str in sys.path:
            sys.path.remove(zip_str)
    importlib.invalidate_caches()


@pytest.mark.skipif(sys.version_info < (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_toml_file_traversable(zip_traversable):
    """A packaged resource passed as a non-Path ``Traversable`` (e.g. from inside a zip/wheel) should load. See #299."""
    trav = zip_traversable('toml_trav_pkg', 'defaults.toml', 'foobar = "Hello"\n')

    class Settings(BaseSettings):
        foobar: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (TomlConfigSettingsSource(settings_cls, toml_file=trav),)

    assert Settings().model_dump() == {'foobar': 'Hello'}


@pytest.mark.skipif(sys.version_info < (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_toml_table_header_traversable(zip_traversable):
    """``toml_table_header`` relies on ``_any_file_exists``, which must handle a non-Path ``Traversable``. See #299."""
    trav = zip_traversable('toml_trav_header_pkg', 'defaults.toml', '[app]\nfoobar = "Hello"\n')

    class Settings(BaseSettings):
        foobar: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (TomlConfigSettingsSource(settings_cls, toml_file=trav, toml_table_header=('app',)),)

    assert Settings().model_dump() == {'foobar': 'Hello'}
