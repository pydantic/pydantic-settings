from typing import List, Tuple, Union

from pydantic.typing import StrPath


class SettingsError(ValueError):
    pass


env_file_sentinel = str(object())
DotenvType = Union[StrPath, List[StrPath], Tuple[StrPath, ...]]
