import json
from functools import lru_cache
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from pydantic import BaseModel
from pydantic.fields import ModelField
from pydantic.typing import get_origin, is_union
from pydantic.utils import lenient_issubclass

from .exceptions import SettingsError


class KeyMapNotFound(Exception):
    pass


class EmptyClass:
    pass


def default_complex_loader(field_name: str, raw_value: str):
    return json.loads(raw_value)


def field_is_complex(field: ModelField) -> Tuple[bool, bool]:
    """
    Find out if a field is complex, and if so whether JSON errors should be ignored
    """
    if field.is_complex():
        allow_parse_failure = False
    elif is_union(get_origin(field.type_)) and field.sub_fields and any(f.is_complex() for f in field.sub_fields):
        allow_parse_failure = True
    else:
        return False, False

    return True, allow_parse_failure


class SourceMapper:
    __slots__ = ('source', 'case_sensitive', 'prefix', 'nesting_delimiter', 'complex_loader')

    def __init__(
        self,
        source: Mapping,
        case_sensitive: bool = False,
        prefix: Optional[str] = None,
        nesting_delimiter: Optional[str] = None,
        complex_loader: Callable = default_complex_loader,
    ):
        self.source = source
        self.prefix = prefix
        self.case_sensitive = case_sensitive
        self.nesting_delimiter = nesting_delimiter
        self.complex_loader = complex_loader

    @property
    @lru_cache()
    def keymap(self) -> Dict[str, str]:
        keydb: Dict[str, str] = {}
        for source_key in self.source.keys():
            key = str(source_key) if self.case_sensitive else str(source_key).lower()
            if key in keydb:
                # Take the first one only
                continue
            keydb[key] = source_key
        return keydb

    def get_value(self, key: str, should_raise: bool = False) -> Any:
        if key not in self.keymap:
            if should_raise:
                raise KeyMapNotFound(f"Key {key} isn't provided any of setting sources")
            return EmptyClass()
        k = self.keymap[key]
        return self.source.get(k)

    def __call__(self, settings: Any) -> Dict[str, Any]:
        """Maps the values from different sources to the settings instance.

        The precedence of the sources are determined by it's order in the list
        The default order is Initkwargs, Environment and secret
        """

        result: Dict[str, Any] = {}
        for field in settings.__fields__.values():
            self.parse_field(field, result, '')
        return result

    def is_parse_failure_allowed(self, field: ModelField):
        return is_union(get_origin(field.type_)) and field.sub_fields and any(f.is_complex() for f in field.sub_fields)

    def parse_field(self, field: ModelField, result: dict, prefix: str = '') -> None:
        """
        Process env_vars and extract the values of keys containing env_nested_delimiter into nested dictionaries.

        This is applied to a single field, hence filtering by env_var prefix.
        """
        env_names = field.field_info.extra.get('env_names', [])
        prefixed_env_names = [f'{prefix}{env}' for env in env_names]
        search_radar = prefixed_env_names if field.name in env_names else env_names
        response = self.deserialize_field(search_radar, field)
        if not isinstance(response, EmptyClass):
            if isinstance(response, dict):
                result.setdefault(field.alias, {}).update(response)
            else:
                result[field.alias] = response
                print("This response can't be non dict")

        if not env_names:
            return
        if lenient_issubclass(field.type_, BaseModel):
            if self.nesting_delimiter is None:
                # Don't parse if nested_delimiter is not specified
                return
            for prefix_without_nesting in prefixed_env_names:
                prefix_with_nesting = f'{prefix_without_nesting}{self.nesting_delimiter}'
                for f in field.type_.__fields__.values():
                    self.parse_field(f, result.setdefault(field.alias, {}), prefix_with_nesting)

    def deserialize_field(self, search_radar: List[str], field: ModelField):
        dict_result = {}
        for key in search_radar:
            value = self.get_value(key)
            if isinstance(value, EmptyClass):
                continue
            # TODO: Could there be no situation that user deliberately sets None as value?
            if value is None:
                continue
            is_complex, is_parse_failure_allowed = field_is_complex(field)
            if is_complex:
                # If field is complex and value is not dict, try to parse it.
                if not isinstance(value, dict):
                    try:
                        value = self.complex_loader(field.name, value)
                    except ValueError as e:
                        if not is_parse_failure_allowed:
                            raise SettingsError(f'error parsing env var "{key}"') from e

            if isinstance(value, dict):
                # Carryon to search for more values of dictionary else return
                dict_result.update(value)
            else:
                return value
        if not dict_result:
            return EmptyClass()
        return dict_result
