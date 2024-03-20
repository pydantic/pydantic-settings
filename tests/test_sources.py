"""Test pydantic_settings.sources."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from pydantic_settings.main import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import PyprojectTomlConfigSettingsSource

try:
    import tomli
except ImportError:
    tomli = None

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


MODULE = 'pydantic_settings.sources'

SOME_TOML_DATA = """
field = "top-level"

[some]
[some.table]
field = "some"

[other.table]
field = "other"
"""


class SimpleSettings(BaseSettings):
    """Simple settings."""

    model_config = SettingsConfigDict(pyproject_toml_depth=1, pyproject_toml_table_header=('some', 'table'))


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
class TestPyprojectTomlConfigSettingsSource:
    """Test PyprojectTomlConfigSettingsSource."""

    def test___init__(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """Test __init__."""
        mocker.patch(f'{MODULE}.Path.cwd', return_value=tmp_path)
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text(SOME_TOML_DATA)
        obj = PyprojectTomlConfigSettingsSource(SimpleSettings)
        assert obj.toml_table_header == ('some', 'table')
        assert obj.toml_data == {'field': 'some'}
        assert obj.toml_file_path == tmp_path / 'pyproject.toml'

    def test___init___explicit(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """Test __init__ explicit file."""
        mocker.patch(f'{MODULE}.Path.cwd', return_value=tmp_path)
        pyproject = tmp_path / 'child' / 'pyproject.toml'
        pyproject.parent.mkdir()
        pyproject.write_text(SOME_TOML_DATA)
        obj = PyprojectTomlConfigSettingsSource(SimpleSettings, pyproject)
        assert obj.toml_table_header == ('some', 'table')
        assert obj.toml_data == {'field': 'some'}
        assert obj.toml_file_path == pyproject

    def test___init___explicit_missing(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """Test __init__ explicit file missing."""
        mocker.patch(f'{MODULE}.Path.cwd', return_value=tmp_path)
        pyproject = tmp_path / 'child' / 'pyproject.toml'
        obj = PyprojectTomlConfigSettingsSource(SimpleSettings, pyproject)
        assert obj.toml_table_header == ('some', 'table')
        assert not obj.toml_data
        assert obj.toml_file_path == pyproject

    @pytest.mark.parametrize('depth', [0, 99])
    def test___init___no_file(self, depth: int, mocker: MockerFixture, tmp_path: Path) -> None:
        """Test __init__ no file."""

        class Settings(BaseSettings):
            model_config = SettingsConfigDict(pyproject_toml_depth=depth)

        mocker.patch(f'{MODULE}.Path.cwd', return_value=tmp_path / 'foo')
        obj = PyprojectTomlConfigSettingsSource(Settings)
        assert obj.toml_table_header == ('tool', 'pydantic-settings')
        assert not obj.toml_data
        assert obj.toml_file_path == tmp_path / 'foo' / 'pyproject.toml'

    def test___init___parent(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """Test __init__ parent directory."""
        mocker.patch(f'{MODULE}.Path.cwd', return_value=tmp_path / 'child')
        pyproject = tmp_path / 'pyproject.toml'
        pyproject.write_text(SOME_TOML_DATA)
        obj = PyprojectTomlConfigSettingsSource(SimpleSettings)
        assert obj.toml_table_header == ('some', 'table')
        assert obj.toml_data == {'field': 'some'}
        assert obj.toml_file_path == tmp_path / 'pyproject.toml'
