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


def default_complex_parser(field_name: str, raw_value: str) -> Mapping[str, Any]:
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
    __slots__ = ('source', 'case_sensitive', 'nesting_delimiter', 'complex_parser', 'get_field_info')

    def __init__(
        self,
        source: Mapping[str, Any],
        get_field_info: Callable[[str], Mapping[str, Any]],
        case_sensitive: bool = False,
        nesting_delimiter: Optional[str] = None,
        complex_parser: Callable[[str, str], Mapping[str, Any]] = default_complex_parser,
    ):
        self.source = source
        self.case_sensitive = case_sensitive
        self.nesting_delimiter = nesting_delimiter
        self.complex_parser = complex_parser
        self.get_field_info = get_field_info

    @property  # type: ignore
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

    def has_env(self, field: ModelField) -> bool:
        field_info = self.get_field_info(field.name)
        env = field_info.get('env') or field.field_info.extra.get('env')
        return env is not None

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
            self.update_result_for_field(field, '', result)
        return result

    def update_result_for_field(self, field: ModelField, prefix: str, result: Dict[str, Any]) -> None:
        """Parses value for given field and populates it to the result dictionary."""
        names = field.field_info.extra.get('env_names', [])
        if not self.has_env(field):
            names = [f'{prefix}{env}' for env in names]

        response = self.get_field_value(names, field)
        if response != _Empty:
            if isinstance(response, dict):
                result.setdefault(field.alias, {}).update(response)
            else:
                result[field.alias] = response

        # In case of nested setting where field is a BaseModel, and if the
        # nesting_delimiter is provided, we would further parse the fields and
        # use the prefix `{name}{nesting_delimiter}` to further parse subfields.
        # If the nesting delimiter is not given, we would assume that the
        # previous deserialize already full dictionary representing subfields
        if lenient_issubclass(field.type_, BaseModel) and self.nesting_delimiter:
            for name in names:
                nesting_prefix = f'{name}{self.nesting_delimiter}'
                for f in field.type_.__fields__.values():
                    self.update_result_for_field(f, nesting_prefix, result.setdefault(field.alias, {}))

    def get_field_value(self, search_radar: List[str], field: ModelField) -> Any:
        dict_result = {}
        for key in search_radar:
            source_key = self.keymap.get(key)  # type: ignore
            if not source_key:
                continue

            value = self.source.get(source_key)
            if value is None:
                # TODO: Perhapse, in some case we intentionally want to pass None value?
                continue

            is_complex, is_parse_failure_allowed = field_is_complex(field)
            if is_complex:
                # If field is complex and value is not dict, try to parse it.
                if not isinstance(value, dict):
                    try:
                        value = self.complex_parser(field.name, value)
                    except ValueError as e:
                        if not is_parse_failure_allowed:
                            raise SettingsError(f'error parsing env var "{key}"') from e

            # If the value is dict, there might be other fractions of dictionary
            # in another key, so instead of returning value, keep on looking
            if isinstance(value, dict):
                # Carryon to search for more values of dictionary else return
                dict_result.update(value)
            else:
                return value

        if not dict_result:
            return _Empty
        return dict_result
