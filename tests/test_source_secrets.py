"""Tests for SecretsSettingsSource and path_type_label broken symlink handling."""

from pathlib import Path

import pytest

from pydantic_settings import BaseSettings
from pydantic_settings.utils import path_type_label


def _mock_broken_symlink(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    """Make ``target`` behave as a dangling symlink without requiring OS symlink privileges."""
    orig_exists = Path.exists
    orig_is_file = Path.is_file
    orig_is_dir = Path.is_dir
    orig_is_mount = Path.is_mount
    orig_is_symlink = Path.is_symlink

    def mock_exists(self, *args, **kwargs):
        if self == target:
            return False
        return orig_exists(self, *args, **kwargs)

    def mock_is_file(self, *args, **kwargs):
        if self == target:
            return False
        return orig_is_file(self, *args, **kwargs)

    def mock_is_dir(self, *args, **kwargs):
        if self == target:
            return False
        return orig_is_dir(self, *args, **kwargs)

    def mock_is_mount(self):
        if self == target:
            return False
        return orig_is_mount(self)

    def mock_is_symlink(self):
        if self == target:
            return True
        return orig_is_symlink(self)

    monkeypatch.setattr(Path, 'exists', mock_exists)
    monkeypatch.setattr(Path, 'is_file', mock_is_file)
    monkeypatch.setattr(Path, 'is_dir', mock_is_dir)
    monkeypatch.setattr(Path, 'is_mount', mock_is_mount)
    monkeypatch.setattr(Path, 'is_symlink', mock_is_symlink)


def test_path_type_label_broken_symlink_mocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    broken = tmp_path / 'broken'
    broken.write_text('placeholder')
    _mock_broken_symlink(monkeypatch, broken)

    assert path_type_label(broken) == 'symlink'

    missing = tmp_path / 'does_not_exist'
    with pytest.raises(AssertionError, match='path does not exist'):
        path_type_label(missing)


def test_path_type_label_broken_symlink(tmp_path: Path) -> None:
    link = tmp_path / 'broken'
    try:
        link.symlink_to(tmp_path / 'missing_target')
    except OSError:
        pytest.skip('symlinks not supported on this platform')

    assert path_type_label(link) == 'symlink'


def test_secrets_broken_symlink_mocked_warns_and_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d1 = tmp_path / 'dir1'
    d2 = tmp_path / 'dir2'
    d1.mkdir()
    d2.mkdir()
    (d1 / 'token').write_text('fallback_secret')
    broken = d2 / 'token'
    broken.write_text('placeholder')
    _mock_broken_symlink(monkeypatch, broken)

    class Settings(BaseSettings):
        token: str | None = None

    with pytest.warns(UserWarning, match='attempted to load secret file .* but found a symlink instead'):
        assert Settings(_secrets_dir=[d1, d2]).token == 'fallback_secret'

    with pytest.warns(UserWarning, match='attempted to load secret file .* but found a symlink instead'):
        assert Settings(_secrets_dir=d2).token is None


def test_secrets_broken_symlink_warns_and_falls_back(tmp_path: Path) -> None:
    d1 = tmp_path / 'dir1'
    d2 = tmp_path / 'dir2'
    d1.mkdir()
    d2.mkdir()
    (d1 / 'token').write_text('fallback_secret')
    link = d2 / 'token'
    try:
        link.symlink_to(tmp_path / 'missing_target')
    except OSError:
        pytest.skip('symlinks not supported on this platform')

    class Settings(BaseSettings):
        token: str | None = None

    with pytest.warns(UserWarning, match='attempted to load secret file .* but found a symlink instead'):
        assert Settings(_secrets_dir=[d1, d2]).token == 'fallback_secret'

    with pytest.warns(UserWarning, match='attempted to load secret file .* but found a symlink instead'):
        assert Settings(_secrets_dir=d2).token is None
