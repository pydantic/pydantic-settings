import os
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic.typing import StrPath
from pydantic.utils import path_type

from .utils import SettingsError

DotenvType = Union[StrPath, List[StrPath], Tuple[StrPath, ...]]


def secret_source(secrets_dir_path: Optional[StrPath] = None) -> Dict[str, Any]:
    secrets = {}
    if not secrets_dir_path:
        return secrets

    secrets_dir_path = Path(secrets_dir_path).expanduser()
    if not secrets_dir_path.exists():
        warnings.warn(f'directory "{secrets_dir_path}" does not exist')
        return secrets

    if not secrets_dir_path.is_dir():
        raise SettingsError(f'secrets_dir must reference a directory, not a {path_type(secrets_dir_path)}')

    for f in secrets_dir_path.iterdir():
        # warnings.warn(
        #     f'attempted to load secret file "{path}" but found a {path_type(path)} instead.',
        #     stacklevel=4,
        # )
        if not f.is_file():
            continue
        secrets[f.name] = f.read_text().strip()
    return secrets


def dotenv_source(env_file_paths: Optional[DotenvType], env_file_encoding: Optional[str] = None) -> Dict[str, Any]:
    try:
        from dotenv import dotenv_values
    except ImportError as e:
        raise ImportError('python-dotenv is not installed, run `pip install pydantic[dotenv]`') from e

    env_file_encoding = env_file_encoding if env_file_encoding else 'utf8'
    dotenv_vars = {}
    if env_file_paths is None:
        return dotenv_vars

    if isinstance(env_file_paths, (str, os.PathLike)):
        env_file_paths = [env_file_paths]

    for file_path in env_file_paths:
        file_path = Path(file_path).expanduser()
        if not file_path.is_file():
            continue
        dotenv_vars.update(dotenv_values(file_path, encoding=env_file_encoding))
    return dotenv_vars


def env_source(env_file_paths: Optional[DotenvType], env_file_encoding: str = 'utf8'):
    env_vars = {}
    if env_file_paths:
        env_vars.update(dotenv_source(env_file_paths, env_file_encoding))
    return {**env_vars, **os.environ}
