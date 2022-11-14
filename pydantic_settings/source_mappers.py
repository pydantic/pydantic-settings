import json
from functools import lru_cache
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

from pydantic import BaseModel
from pydantic.fields import ModelField
from pydantic.typing import get_origin, is_union
from pydantic.utils import lenient_issubclass

from .utils import SettingsError


class _Empty:
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
        source: Mapping[str, Any],
        case_sensitive: bool = False,
        nesting_delimiter: Optional[str] = None,
        complex_loader: Callable = default_complex_loader,
    ):
        self.source = source
        self.case_sensitive = case_sensitive
        self.nesting_delimiter = nesting_delimiter
        self.complex_loader = complex_loader

    @property
    @lru_cache()
    def keymap(self) -> Dict[str, str]:
        """Builds a keymap that holds the mapping keys that follows SourceMapper
        heurestics such as case_sensitivity to the original key of the provider.
        """
        keydb: Dict[str, str] = {}
        for source_key in self.source.keys():
            key = str(source_key) if self.case_sensitive else str(source_key).lower()
            if key in keydb:
                # If the key has already been parsed, it will be ignored. User
                # should be mindful about the keys with same name in different
                # cases.
                continue
            keydb[key] = source_key
        return keydb

    def get_value_from_source(self, key: str, should_raise: bool = False) -> Any:
        if key not in self.keymap:
            if should_raise:
                raise SettingsError(f"Key {key} isn't provided any of setting sources")
            return _Empty
        k = self.keymap[key]
        return self.source.get(k)

    def __call__(self, fields: Iterator[ModelField]) -> Dict[str, Any]:
        """Generates mapping between the settings field to values from the
        source based on heurestics defined by user.

        The mapping only consists of the the result for matched fields.
        Therefore, there aren't any extras coming from the SourceMapper.
        """

        result: Dict[str, Any] = {}
        for field in fields:
            # Since the fields are alreay prefixed by Config, we don't need a
            # seed prefix here.
            self.parse_field(field, result, '')
        return result

    def parse_field(self, field: ModelField, result: Dict[str, Any], prefix: str = '') -> None:
        """Parses value for given field and populates it to the result dictionary."""
        env_names = field.field_info.extra.get('env_names', [])
        prefixed_env_names = [f'{prefix}{env}' for env in env_names]
        search_radar = prefixed_env_names if field.name in env_names else env_names
        response = self.deserialize_field(search_radar, field)
        if response != _Empty:
            if isinstance(response, dict):
                result.setdefault(field.alias, {}).update(response)
            else:
                result[field.alias] = response

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
            value = self.get_value_from_source(key)
            if value == _Empty:
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
            return _Empty
        return dict_result
