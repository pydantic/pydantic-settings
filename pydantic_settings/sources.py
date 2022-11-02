import json
from functools import lru_cache
from multiprocessing.sharedctypes import Value
from typing import Any, Dict, List, Mapping, Optional, NamedTuple, Set, Tuple

from pydantic import BaseModel
from pydantic.typing import get_origin, is_union
from pydantic.utils import deep_update, path_type, sequence_like, lenient_issubclass
from pydantic.config import BaseConfig, Extra
from pydantic.fields import ModelField, Field
from pytest_mock import package_mocker

class SettingsError(ValueError):
    pass

class KeyMap(NamedTuple):
    key: str

class KeyMapNotFound(Exception):
    pass

class EmptyClass: pass

# TODO: Need to treat the init special class seperately e.g. having it's own class.
class SettingsSource:
    __slots__ = ("source", "case_sensitive", "prefix", "nesting_delimiter", "prefix_len")
    
    def __init__(self, source: Mapping, case_sensitive: bool = False, prefix: Optional[str]=None, nesting_delimiter: Optional[str] = None):
        self.source = source
        self.prefix = prefix
        self.case_sensitive = case_sensitive
        self.nesting_delimiter = nesting_delimiter
    
    @lru_cache()
    def build_key_to_source_map(self) -> Dict[str, KeyMap]:
        keydb: Dict[str, KeyMap] = {}
        for source_key in self.source.keys():
            key = (
                str(source_key) if self.case_sensitive else str(source_key).lower()
            )
            if key in keydb:
                # Take the first one only
                continue
            keydb[key] = KeyMap(key=source_key)
        return keydb

    def get_value(self, key: str, should_raise: bool = False)-> Any:
        keydb = self.build_key_to_source_map()
        if key not in keydb:
            if should_raise:
                raise KeyMapNotFound(f"Key {key} isn't provided any of setting sources")
            return EmptyClass()
        k = keydb[key]
        return self.source.get(k.key)

    
    def __call__(self, settings: Any) -> Dict[str, Any]:
        """Maps the values from different sources to the settings instance.

        The precedence of the sources are determined by it's order in the list
        The default order is Initkwargs, Environment and secret
        """

        result: Dict[str, Any] = {}        
        for field in settings.__fields__.values():
            self.parse_field(field, result, "")
        return result
    
    def is_parse_failure_allowed(self, field: ModelField):
        return is_union(get_origin(field.type_)) and field.sub_fields and any(f.is_complex() for f in field.sub_fields)


    def parse_field(self, field: ModelField, result: dict, prefix: str="") -> None:
        """
        Process env_vars and extract the values of keys containing env_nested_delimiter into nested dictionaries.

        This is applied to a single field, hence filtering by env_var prefix.
        """
        # TODO: If the end field type_isn't mapping don't make big fuss, else construct the field name
        # TODO: Use regex pattern for only the field with the end type mapping
        # TODO: Prepare_field should create a probable env names
        # TODO: Regex match the fields with complex so that even though there's delimiter within the field name it could be matched.
        env_names = field.field_info.extra.get("env_names")
        if not env_names: 
            print(field.name)
        prefixed_env_names = [f"{prefix}{env}" for env in env_names]
        search_radar = prefixed_env_names if field.name in env_names else env_names
        response = self.deserialize_field(search_radar, field)
        if not isinstance(response, EmptyClass):
            if isinstance(response, dict):
                result.setdefault(field.alias, {}).update(response)
            else:
                result[field.alias] = response
                print("This response can't be non dict")

        if not env_names: return # TODO: The pydantic types like DateTime, URL are indeed a lenient subclass but the subfields doesn't have env_names and should't be populated as well
        if lenient_issubclass(field.type_, BaseModel):
            if self.nesting_delimiter is None:
                # Don't parse if nested_delimiter is not specified
                return
            for prefix_without_nesting in prefixed_env_names:
                prefix_with_nesting = f"{prefix_without_nesting}{self.nesting_delimiter}"
                for f in field.type_.__fields__.values():
                    self.parse_field(f, result.setdefault(field.alias, {}), prefix_with_nesting)
    

    def deserialize_field(self, search_radar:List[str], field: ModelField):
        dict_result = {}
        for key in search_radar:
            value = self.get_value(key)
            if isinstance(value, EmptyClass):
                continue
            
            if field.is_complex():
                # If field is complex and value is not dict, try to parse it.
                if not isinstance(value, dict):
                    try:
                        value = json.loads(value)
                    except ValueError as e:
                        if not self.is_parse_failure_allowed(field):
                            raise SettingsError(f'error parsing env var "{key}"') from e
            if isinstance(value, dict):
                # Carryon to search for more values of dictionary else return
                dict_result.update(value)
            else:
                return value
        if not dict_result:
            return EmptyClass()
        return dict_result




