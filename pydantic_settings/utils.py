import logging
import os
import types
from pathlib import Path
from typing import Any, _Final, _GenericAlias, get_origin  # type: ignore [attr-defined]

logger = logging.getLogger('pydantic_settings')

_DEBUG_ENV_VAR = 'PYDANTIC_SETTINGS_DEBUG'


def _settings_debug_enabled() -> bool:
    """Whether settings source debugging is enabled via the `PYDANTIC_SETTINGS_DEBUG` env var."""
    return os.environ.get(_DEBUG_ENV_VAR, '').strip().lower() in ('1', 'true', 'yes', 'on')


_PATH_TYPE_LABELS: tuple[tuple[str, str], ...] = (
    ('is_dir', 'directory'),
    ('is_file', 'file'),
    ('is_mount', 'mount point'),
    ('is_symlink', 'symlink'),
    ('is_block_device', 'block device'),
    ('is_char_device', 'char device'),
    ('is_fifo', 'FIFO'),
    ('is_socket', 'socket'),
)


def path_type_label(p: Path) -> str:
    """
    Find out what sort of thing a path is.
    """
    assert p.exists(), 'path does not exist'
    for method_name, name in _PATH_TYPE_LABELS:
        if getattr(p, method_name)():
            return name

    return 'unknown'  # pragma: no cover


# TODO remove and replace usage by `isinstance(cls, type) and issubclass(cls, class_or_tuple)`
# once we drop support for Python 3.10.
def _lenient_issubclass(cls: Any, class_or_tuple: Any) -> bool:  # pragma: no cover
    try:
        return isinstance(cls, type) and issubclass(cls, class_or_tuple)
    except TypeError:
        if get_origin(cls) is not None:
            # Up until Python 3.10, isinstance(<generic_alias>, type) is True
            # for generic aliases such as `list[int]`
            return False
        raise


_WithArgsTypes = (_GenericAlias, types.GenericAlias, types.UnionType)
_typing_base: Any = _Final  # pyright: ignore[reportAttributeAccessIssue]
