import argparse
import dataclasses
import json
import os
import re
import sys
import typing
import uuid
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Dict, Generic, Hashable, List, Optional, Set, Tuple, Type, TypeVar, Union

import pytest
import typing_extensions
from annotated_types import MinLen
from pydantic import (
    AliasChoices,
    AliasPath,
    BaseModel,
    DirectoryPath,
    Discriminator,
    Field,
    HttpUrl,
    Json,
    RootModel,
    SecretStr,
    Tag,
    ValidationError,
)
from pydantic import (
    dataclasses as pydantic_dataclasses,
)
from pydantic._internal._repr import Representation
from pydantic.fields import FieldInfo
from pytest_mock import MockerFixture
from typing_extensions import Annotated, Literal

from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    InitSettingsSource,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    PyprojectTomlConfigSettingsSource,
    SecretsSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
    YamlConfigSettingsSource,
)
from pydantic_settings.sources import CliPositionalArg, CliSettingsSource, CliSubCommand, SettingsError, read_env_file

try:
    import dotenv
except ImportError:
    dotenv = None
try:
    import yaml
except ImportError:
    yaml = None
try:
    import tomli
except ImportError:
    tomli = None


def foobar(a, b, c=4):
    pass


T = TypeVar('T')


class FruitsEnum(IntEnum):
    pear = 0
    kiwi = 1
    lime = 2


class CliDummyArgGroup(BaseModel, arbitrary_types_allowed=True):
    group: argparse._ArgumentGroup

    def add_argument(self, *args, **kwargs) -> None:
        self.group.add_argument(*args, **kwargs)


class CliDummySubParsers(BaseModel, arbitrary_types_allowed=True):
    sub_parser: argparse._SubParsersAction

    def add_parser(self, *args, **kwargs) -> 'CliDummyParser':
        return CliDummyParser(parser=self.sub_parser.add_parser(*args, **kwargs))


class CliDummyParser(BaseModel, arbitrary_types_allowed=True):
    parser: argparse.ArgumentParser = Field(default_factory=lambda: argparse.ArgumentParser())

    def add_argument(self, *args, **kwargs) -> None:
        self.parser.add_argument(*args, **kwargs)

    def add_argument_group(self, *args, **kwargs) -> CliDummyArgGroup:
        return CliDummyArgGroup(group=self.parser.add_argument_group(*args, **kwargs))

    def add_subparsers(self, *args, **kwargs) -> CliDummySubParsers:
        return CliDummySubParsers(sub_parser=self.parser.add_subparsers(*args, **kwargs))

    def parse_args(self, *args, **kwargs) -> argparse.Namespace:
        return self.parser.parse_args(*args, **kwargs)


class LoggedVar(Generic[T]):
    def get(self) -> T: ...


class SimpleSettings(BaseSettings):
    apple: str


class SettingWithIgnoreEmpty(BaseSettings):
    apple: str = 'default'

    model_config = SettingsConfigDict(env_ignore_empty=True)


def test_sub_env(env):
    env.set('apple', 'hello')
    s = SimpleSettings()
    assert s.apple == 'hello'


def test_sub_env_override(env):
    env.set('apple', 'hello')
    s = SimpleSettings(apple='goodbye')
    assert s.apple == 'goodbye'


def test_sub_env_missing():
    with pytest.raises(ValidationError) as exc_info:
        SimpleSettings()
    assert exc_info.value.errors(include_url=False) == [
        {'type': 'missing', 'loc': ('apple',), 'msg': 'Field required', 'input': {}}
    ]


def test_other_setting():
    with pytest.raises(ValidationError):
        SimpleSettings(apple='a', foobar=42)


def test_ignore_empty_when_empty_uses_default(env):
    env.set('apple', '')
    s = SettingWithIgnoreEmpty()
    assert s.apple == 'default'


def test_ignore_empty_when_not_empty_uses_value(env):
    env.set('apple', 'a')
    s = SettingWithIgnoreEmpty()
    assert s.apple == 'a'


def test_ignore_empty_with_dotenv_when_empty_uses_default(tmp_path):
    p = tmp_path / '.env'
    p.write_text('a=')

    class Settings(BaseSettings):
        a: str = 'default'

        model_config = SettingsConfigDict(env_file=p, env_ignore_empty=True)

    s = Settings()
    assert s.a == 'default'


def test_ignore_empty_with_dotenv_when_not_empty_uses_value(tmp_path):
    p = tmp_path / '.env'
    p.write_text('a=b')

    class Settings(BaseSettings):
        a: str = 'default'

        model_config = SettingsConfigDict(env_file=p, env_ignore_empty=True)

    s = Settings()
    assert s.a == 'b'


def test_with_prefix(env):
    class Settings(BaseSettings):
        apple: str

        model_config = SettingsConfigDict(env_prefix='foobar_')

    with pytest.raises(ValidationError):
        Settings()
    env.set('foobar_apple', 'has_prefix')
    s = Settings()
    assert s.apple == 'has_prefix'


def test_nested_env_with_basemodel(env):
    class TopValue(BaseModel):
        apple: str
        banana: str

    class Settings(BaseSettings):
        top: TopValue

    with pytest.raises(ValidationError):
        Settings()
    env.set('top', '{"banana": "secret_value"}')
    s = Settings(top={'apple': 'value'})
    assert s.top.apple == 'value'
    assert s.top.banana == 'secret_value'


def test_merge_dict(env):
    class Settings(BaseSettings):
        top: Dict[str, str]

    with pytest.raises(ValidationError):
        Settings()
    env.set('top', '{"banana": "secret_value"}')
    s = Settings(top={'apple': 'value'})
    assert s.top == {'apple': 'value', 'banana': 'secret_value'}


def test_nested_env_delimiter(env):
    class SubSubValue(BaseSettings):
        v6: str

    class SubValue(BaseSettings):
        v4: str
        v5: int
        sub_sub: SubSubValue

    class TopValue(BaseSettings):
        v1: str
        v2: str
        v3: str
        sub: SubValue

    class Cfg(BaseSettings):
        v0: str
        v0_union: Union[SubValue, int]
        top: TopValue

        model_config = SettingsConfigDict(env_nested_delimiter='__')

    env.set('top', '{"v1": "json-1", "v2": "json-2", "sub": {"v5": "xx"}}')
    env.set('top__sub__v5', '5')
    env.set('v0', '0')
    env.set('top__v2', '2')
    env.set('top__v3', '3')
    env.set('v0_union', '0')
    env.set('top__sub__sub_sub__v6', '6')
    env.set('top__sub__v4', '4')
    cfg = Cfg()
    assert cfg.model_dump() == {
        'v0': '0',
        'v0_union': 0,
        'top': {
            'v1': 'json-1',
            'v2': '2',
            'v3': '3',
            'sub': {'v4': '4', 'v5': 5, 'sub_sub': {'v6': '6'}},
        },
    }


def test_nested_env_optional_json(env):
    class Child(BaseModel):
        num_list: Optional[List[int]] = None

    class Cfg(BaseSettings, env_nested_delimiter='__'):
        child: Optional[Child] = None

    env.set('CHILD__NUM_LIST', '[1,2,3]')
    cfg = Cfg()
    assert cfg.model_dump() == {
        'child': {
            'num_list': [1, 2, 3],
        },
    }


def test_nested_env_delimiter_with_prefix(env):
    class Subsettings(BaseSettings):
        banana: str

    class Settings(BaseSettings):
        subsettings: Subsettings

        model_config = SettingsConfigDict(env_nested_delimiter='_', env_prefix='myprefix_')

    env.set('myprefix_subsettings_banana', 'banana')
    s = Settings()
    assert s.subsettings.banana == 'banana'

    class Settings(BaseSettings):
        subsettings: Subsettings

        model_config = SettingsConfigDict(env_nested_delimiter='_', env_prefix='myprefix__')

    env.set('myprefix__subsettings_banana', 'banana')
    s = Settings()
    assert s.subsettings.banana == 'banana'


def test_nested_env_delimiter_complex_required(env):
    class Cfg(BaseSettings):
        v: str = 'default'

        model_config = SettingsConfigDict(env_nested_delimiter='__')

    env.set('v__x', 'x')
    env.set('v__y', 'y')
    cfg = Cfg()
    assert cfg.model_dump() == {'v': 'default'}


def test_nested_env_delimiter_aliases(env):
    class SubModel(BaseModel):
        v1: str
        v2: str

    class Cfg(BaseSettings):
        sub_model: SubModel = Field(validation_alias=AliasChoices('foo', 'bar'))

        model_config = SettingsConfigDict(env_nested_delimiter='__')

    env.set('foo__v1', '-1-')
    env.set('bar__v2', '-2-')
    assert Cfg().model_dump() == {'sub_model': {'v1': '-1-', 'v2': '-2-'}}


class DateModel(BaseModel):
    pips: bool = False


class ComplexSettings(BaseSettings):
    apples: List[str] = []
    bananas: Set[int] = set()
    carrots: dict = {}
    date: DateModel = DateModel()


def test_list(env):
    env.set('apples', '["russet", "granny smith"]')
    s = ComplexSettings()
    assert s.apples == ['russet', 'granny smith']
    assert s.date.pips is False


def test_annotated_list(env):
    class AnnotatedComplexSettings(BaseSettings):
        apples: Annotated[List[str], MinLen(2)] = []

    env.set('apples', '["russet", "granny smith"]')
    s = AnnotatedComplexSettings()
    assert s.apples == ['russet', 'granny smith']

    env.set('apples', '["russet"]')
    with pytest.raises(ValidationError) as exc_info:
        AnnotatedComplexSettings()
    assert exc_info.value.errors(include_url=False) == [
        {
            'ctx': {'actual_length': 1, 'field_type': 'List', 'min_length': 2},
            'input': ['russet'],
            'loc': ('apples',),
            'msg': 'List should have at least 2 items after validation, not 1',
            'type': 'too_short',
        }
    ]


def test_set_dict_model(env):
    env.set('bananas', '[1, 2, 3, 3]')
    env.set('CARROTS', '{"a": null, "b": 4}')
    env.set('daTE', '{"pips": true}')
    s = ComplexSettings()
    assert s.bananas == {1, 2, 3}
    assert s.carrots == {'a': None, 'b': 4}
    assert s.date.pips is True


def test_invalid_json(env):
    env.set('apples', '["russet", "granny smith",]')
    with pytest.raises(SettingsError, match='error parsing value for field "apples" from source "EnvSettingsSource"'):
        ComplexSettings()


def test_required_sub_model(env):
    class Settings(BaseSettings):
        foobar: DateModel

    with pytest.raises(ValidationError):
        Settings()
    env.set('FOOBAR', '{"pips": "TRUE"}')
    s = Settings()
    assert s.foobar.pips is True


def test_non_class(env):
    class Settings(BaseSettings):
        foobar: Optional[str]

    env.set('FOOBAR', 'xxx')
    s = Settings()
    assert s.foobar == 'xxx'


@pytest.mark.parametrize('dataclass_decorator', (pydantic_dataclasses.dataclass, dataclasses.dataclass))
def test_generic_dataclass(env, dataclass_decorator):
    T = TypeVar('T')

    @dataclass_decorator
    class GenericDataclass(Generic[T]):
        x: T

    class ComplexSettings(BaseSettings):
        field: GenericDataclass[int]

    env.set('field', '{"x": 1}')
    s = ComplexSettings()
    assert s.field.x == 1

    env.set('field', '{"x": "a"}')
    with pytest.raises(ValidationError) as exc_info:
        ComplexSettings()
    assert exc_info.value.errors(include_url=False) == [
        {
            'input': 'a',
            'loc': ('field', 'x'),
            'msg': 'Input should be a valid integer, unable to parse string as an integer',
            'type': 'int_parsing',
        }
    ]


def test_generic_basemodel(env):
    T = TypeVar('T')

    class GenericModel(BaseModel, Generic[T]):
        x: T

    class ComplexSettings(BaseSettings):
        field: GenericModel[int]

    env.set('field', '{"x": 1}')
    s = ComplexSettings()
    assert s.field.x == 1

    env.set('field', '{"x": "a"}')
    with pytest.raises(ValidationError) as exc_info:
        ComplexSettings()
    assert exc_info.value.errors(include_url=False) == [
        {
            'input': 'a',
            'loc': ('field', 'x'),
            'msg': 'Input should be a valid integer, unable to parse string as an integer',
            'type': 'int_parsing',
        }
    ]


def test_annotated(env):
    T = TypeVar('T')

    class GenericModel(BaseModel, Generic[T]):
        x: T

    class ComplexSettings(BaseSettings):
        field: GenericModel[int]

    env.set('field', '{"x": 1}')
    s = ComplexSettings()
    assert s.field.x == 1

    env.set('field', '{"x": "a"}')
    with pytest.raises(ValidationError) as exc_info:
        ComplexSettings()
    assert exc_info.value.errors(include_url=False) == [
        {
            'input': 'a',
            'loc': ('field', 'x'),
            'msg': 'Input should be a valid integer, unable to parse string as an integer',
            'type': 'int_parsing',
        }
    ]


def test_env_str(env):
    class Settings(BaseSettings):
        apple: str = Field(None, validation_alias='BOOM')

    env.set('BOOM', 'hello')
    assert Settings().apple == 'hello'


def test_env_list(env):
    class Settings(BaseSettings):
        foobar: str = Field(validation_alias=AliasChoices('different1', 'different2'))

    env.set('different1', 'value 1')
    env.set('different2', 'value 2')
    s = Settings()
    assert s.foobar == 'value 1'


def test_env_list_field(env):
    class Settings(BaseSettings):
        foobar: str = Field(validation_alias='foobar_env_name')

    env.set('FOOBAR_ENV_NAME', 'env value')
    s = Settings()
    assert s.foobar == 'env value'


def test_env_list_last(env):
    class Settings(BaseSettings):
        foobar: str = Field(validation_alias=AliasChoices('different2'))

    env.set('different1', 'value 1')
    env.set('different2', 'value 2')
    s = Settings()
    assert s.foobar == 'value 2'


def test_env_inheritance_field(env):
    class SettingsParent(BaseSettings):
        foobar: str = Field('parent default', validation_alias='foobar_env')

    class SettingsChild(SettingsParent):
        foobar: str = 'child default'

    assert SettingsParent().foobar == 'parent default'

    assert SettingsChild().foobar == 'child default'
    assert SettingsChild(foobar='abc').foobar == 'abc'
    env.set('foobar_env', 'env value')
    assert SettingsParent().foobar == 'env value'
    assert SettingsChild().foobar == 'child default'
    assert SettingsChild(foobar='abc').foobar == 'abc'


def test_env_inheritance_config(env):
    env.set('foobar', 'foobar')
    env.set('prefix_foobar', 'prefix_foobar')

    env.set('foobar_parent_from_field', 'foobar_parent_from_field')
    env.set('prefix_foobar_parent_from_field', 'prefix_foobar_parent_from_field')

    env.set('foobar_parent_from_config', 'foobar_parent_from_config')
    env.set('foobar_child_from_config', 'foobar_child_from_config')

    env.set('foobar_child_from_field', 'foobar_child_from_field')

    # a. Child class config overrides prefix
    class Parent(BaseSettings):
        foobar: str = Field(None, validation_alias='foobar_parent_from_field')

        model_config = SettingsConfigDict(env_prefix='p_')

    class Child(Parent):
        model_config = SettingsConfigDict(env_prefix='prefix_')

    assert Child().foobar == 'foobar_parent_from_field'

    # b. Child class overrides field
    class Parent(BaseSettings):
        foobar: str = Field(None, validation_alias='foobar_parent_from_config')

    class Child(Parent):
        foobar: str = Field(None, validation_alias='foobar_child_from_config')

    assert Child().foobar == 'foobar_child_from_config'

    # . Child class overrides parent prefix and field
    class Parent(BaseSettings):
        foobar: Optional[str]

        model_config = SettingsConfigDict(env_prefix='p_')

    class Child(Parent):
        foobar: str = Field(None, validation_alias='foobar_child_from_field')

        model_config = SettingsConfigDict(env_prefix='prefix_')

    assert Child().foobar == 'foobar_child_from_field'


def test_invalid_validation_alias(env):
    with pytest.raises(
        TypeError, match='Invalid `validation_alias` type. it should be `str`, `AliasChoices`, or `AliasPath`'
    ):

        class Settings(BaseSettings):
            foobar: str = Field(validation_alias=123)


def test_validation_aliases(env):
    class Settings(BaseSettings):
        foobar: str = Field('default value', validation_alias='foobar_alias')

    assert Settings().foobar == 'default value'
    assert Settings(foobar_alias='42').foobar == '42'
    env.set('foobar_alias', 'xxx')
    assert Settings().foobar == 'xxx'
    assert Settings(foobar_alias='42').foobar == '42'


def test_validation_aliases_alias_path(env):
    class Settings(BaseSettings):
        foobar: str = Field(validation_alias=AliasPath('foo', 'bar', 1))

    env.set('foo', '{"bar": ["val0", "val1"]}')
    assert Settings().foobar == 'val1'


def test_validation_aliases_alias_choices(env):
    class Settings(BaseSettings):
        foobar: str = Field(validation_alias=AliasChoices('foo', AliasPath('foo1', 'bar', 1), AliasPath('bar', 2)))

    env.set('foo', 'val1')
    assert Settings().foobar == 'val1'

    env.pop('foo')
    env.set('foo1', '{"bar": ["val0", "val2"]}')
    assert Settings().foobar == 'val2'

    env.pop('foo1')
    env.set('bar', '["val1", "val2", "val3"]')
    assert Settings().foobar == 'val3'


def test_validation_alias_with_env_prefix(env):
    class Settings(BaseSettings):
        foobar: str = Field(validation_alias='foo')

        model_config = SettingsConfigDict(env_prefix='p_')

    env.set('p_foo', 'bar')
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert exc_info.value.errors(include_url=False) == [
        {'type': 'missing', 'loc': ('foo',), 'msg': 'Field required', 'input': {}}
    ]

    env.set('foo', 'bar')
    assert Settings().foobar == 'bar'


def test_case_sensitive(monkeypatch):
    class Settings(BaseSettings):
        foo: str

        model_config = SettingsConfigDict(case_sensitive=True)

    # Need to patch os.environ to get build to work on Windows, where os.environ is case insensitive
    monkeypatch.setattr(os, 'environ', value={'Foo': 'foo'})
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert exc_info.value.errors(include_url=False) == [
        {'type': 'missing', 'loc': ('foo',), 'msg': 'Field required', 'input': {}}
    ]


def test_nested_dataclass(env):
    @pydantic_dataclasses.dataclass
    class MyDataclass:
        foo: int
        bar: str

    class Settings(BaseSettings):
        n: MyDataclass

    env.set('N', '{"foo": 123, "bar": "bar value"}')
    s = Settings()
    assert isinstance(s.n, MyDataclass)
    assert s.n.foo == 123
    assert s.n.bar == 'bar value'


def test_env_takes_precedence(env):
    class Settings(BaseSettings):
        foo: int
        bar: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return env_settings, init_settings

    env.set('BAR', 'env setting')

    s = Settings(foo='123', bar='argument')
    assert s.foo == 123
    assert s.bar == 'env setting'


def test_config_file_settings_nornir(env):
    """
    See https://github.com/pydantic/pydantic/pull/341#issuecomment-450378771
    """

    def nornir_settings_source() -> Dict[str, Any]:
        return {'param_a': 'config a', 'param_b': 'config b', 'param_c': 'config c'}

    class Settings(BaseSettings):
        param_a: str
        param_b: str
        param_c: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return env_settings, init_settings, nornir_settings_source

    env.set('PARAM_C', 'env setting c')

    s = Settings(param_b='argument b', param_c='argument c')
    assert s.param_a == 'config a'
    assert s.param_b == 'argument b'
    assert s.param_c == 'env setting c'


def test_env_union_with_complex_subfields_parses_json(env):
    class A(BaseModel):
        a: str

    class B(BaseModel):
        b: int

    class Settings(BaseSettings):
        content: Union[A, B, int]

    env.set('content', '{"a": "test"}')
    s = Settings()
    assert s.content == A(a='test')


def test_env_union_with_complex_subfields_parses_plain_if_json_fails(env):
    class A(BaseModel):
        a: str

    class B(BaseModel):
        b: int

    class Settings(BaseSettings):
        content: Union[A, B, datetime]

    env.set('content', '{"a": "test"}')
    s = Settings()
    assert s.content == A(a='test')

    env.set('content', '2020-07-05T00:00:00Z')
    s = Settings()
    assert s.content == datetime(2020, 7, 5, 0, 0, tzinfo=timezone.utc)


def test_env_union_without_complex_subfields_does_not_parse_json(env):
    class Settings(BaseSettings):
        content: Union[datetime, str]

    env.set('content', '2020-07-05T00:00:00Z')
    s = Settings()
    assert s.content == '2020-07-05T00:00:00Z'


test_env_file = """\
# this is a comment
A=good string
# another one, followed by whitespace

b='better string'
c="best string"
"""


def test_env_file_config(env, tmp_path):
    p = tmp_path / '.env'
    p.write_text(test_env_file)

    class Settings(BaseSettings):
        a: str
        b: str
        c: str

        model_config = SettingsConfigDict(env_file=p)

    env.set('A', 'overridden var')

    s = Settings()
    assert s.a == 'overridden var'
    assert s.b == 'better string'
    assert s.c == 'best string'


prefix_test_env_file = """\
# this is a comment
prefix_A=good string
# another one, followed by whitespace

prefix_b='better string'
prefix_c="best string"
"""


def test_env_file_with_env_prefix(env, tmp_path):
    p = tmp_path / '.env'
    p.write_text(prefix_test_env_file)

    class Settings(BaseSettings):
        a: str
        b: str
        c: str

        model_config = SettingsConfigDict(env_file=p, env_prefix='prefix_')

    env.set('prefix_A', 'overridden var')

    s = Settings()
    assert s.a == 'overridden var'
    assert s.b == 'better string'
    assert s.c == 'best string'


prefix_test_env_invalid_file = """\
# this is a comment
prefix_A=good string
# another one, followed by whitespace

prefix_b='better string'
prefix_c="best string"
f="random value"
"""


def test_env_file_with_env_prefix_invalid(tmp_path):
    p = tmp_path / '.env'
    p.write_text(prefix_test_env_invalid_file)

    class Settings(BaseSettings):
        a: str
        b: str
        c: str

        model_config = SettingsConfigDict(env_file=p, env_prefix='prefix_')

    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert exc_info.value.errors(include_url=False) == [
        {'type': 'extra_forbidden', 'loc': ('f',), 'msg': 'Extra inputs are not permitted', 'input': 'random value'}
    ]


def test_ignore_env_file_with_env_prefix_invalid(tmp_path):
    p = tmp_path / '.env'
    p.write_text(prefix_test_env_invalid_file)

    class Settings(BaseSettings):
        a: str
        b: str
        c: str

        model_config = SettingsConfigDict(env_file=p, env_prefix='prefix_', extra='ignore')

    s = Settings()

    assert s.a == 'good string'
    assert s.b == 'better string'
    assert s.c == 'best string'


def test_env_file_config_case_sensitive(tmp_path):
    p = tmp_path / '.env'
    p.write_text(test_env_file)

    class Settings(BaseSettings):
        a: str
        b: str
        c: str

        model_config = SettingsConfigDict(env_file=p, case_sensitive=True, extra='ignore')

    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert exc_info.value.errors(include_url=False) == [
        {
            'type': 'missing',
            'loc': ('a',),
            'msg': 'Field required',
            'input': {'b': 'better string', 'c': 'best string', 'A': 'good string'},
        }
    ]


def test_env_file_export(env, tmp_path):
    p = tmp_path / '.env'
    p.write_text(
        """\
export A='good string'
export B=better-string
export C="best string"
"""
    )

    class Settings(BaseSettings):
        a: str
        b: str
        c: str

        model_config = SettingsConfigDict(env_file=p)

    env.set('A', 'overridden var')

    s = Settings()
    assert s.a == 'overridden var'
    assert s.b == 'better-string'
    assert s.c == 'best string'


def test_env_file_export_validation_alias(env, tmp_path):
    p = tmp_path / '.env'
    p.write_text("""export a='{"b": ["1", "2"]}'""")

    class Settings(BaseSettings):
        a: str = Field(validation_alias=AliasChoices(AliasPath('a', 'b', 1)))

        model_config = SettingsConfigDict(env_file=p)

    s = Settings()
    assert s.a == '2'


def test_env_file_config_custom_encoding(tmp_path):
    p = tmp_path / '.env'
    p.write_text('pika=p!±@', encoding='latin-1')

    class Settings(BaseSettings):
        pika: str

        model_config = SettingsConfigDict(env_file=p, env_file_encoding='latin-1')

    s = Settings()
    assert s.pika == 'p!±@'


@pytest.fixture
def home_tmp():
    tmp_filename = f'{uuid.uuid4()}.env'
    home_tmp_path = Path.home() / tmp_filename
    yield home_tmp_path, tmp_filename
    home_tmp_path.unlink()


def test_env_file_home_directory(home_tmp):
    home_tmp_path, tmp_filename = home_tmp
    home_tmp_path.write_text('pika=baz')

    class Settings(BaseSettings):
        pika: str

        model_config = SettingsConfigDict(env_file=f'~/{tmp_filename}')

    assert Settings().pika == 'baz'


def test_env_file_none(tmp_path):
    p = tmp_path / '.env'
    p.write_text('a')

    class Settings(BaseSettings):
        a: str = 'xxx'

    s = Settings(_env_file=p)
    assert s.a == 'xxx'


def test_env_file_override_file(tmp_path):
    p1 = tmp_path / '.env'
    p1.write_text(test_env_file)
    p2 = tmp_path / '.env.prod'
    p2.write_text('A="new string"')

    class Settings(BaseSettings):
        a: str

        model_config = SettingsConfigDict(env_file=str(p1))

    s = Settings(_env_file=p2)
    assert s.a == 'new string'


def test_env_file_override_none(tmp_path):
    p = tmp_path / '.env'
    p.write_text(test_env_file)

    class Settings(BaseSettings):
        a: Optional[str] = None

        model_config = SettingsConfigDict(env_file=p)

    s = Settings(_env_file=None)
    assert s.a is None


def test_env_file_not_a_file(env):
    class Settings(BaseSettings):
        a: str = None

    env.set('A', 'ignore non-file')
    s = Settings(_env_file='tests/')
    assert s.a == 'ignore non-file'


def test_read_env_file_case_sensitive(tmp_path):
    p = tmp_path / '.env'
    p.write_text('a="test"\nB=123')

    assert read_env_file(p) == {'a': 'test', 'b': '123'}
    assert read_env_file(p, case_sensitive=True) == {'a': 'test', 'B': '123'}


def test_read_env_file_syntax_wrong(tmp_path):
    p = tmp_path / '.env'
    p.write_text('NOT_AN_ASSIGNMENT')

    assert read_env_file(p, case_sensitive=True) == {'NOT_AN_ASSIGNMENT': None}


def test_env_file_example(tmp_path):
    p = tmp_path / '.env'
    p.write_text(
        """\
# ignore comment
ENVIRONMENT="production"
REDIS_ADDRESS=localhost:6379
MEANING_OF_LIFE=42
MY_VAR='Hello world'
"""
    )

    class Settings(BaseSettings):
        environment: str
        redis_address: str
        meaning_of_life: int
        my_var: str

    s = Settings(_env_file=str(p))
    assert s.model_dump() == {
        'environment': 'production',
        'redis_address': 'localhost:6379',
        'meaning_of_life': 42,
        'my_var': 'Hello world',
    }


def test_env_file_custom_encoding(tmp_path):
    p = tmp_path / '.env'
    p.write_text('pika=p!±@', encoding='latin-1')

    class Settings(BaseSettings):
        pika: str

    with pytest.raises(UnicodeDecodeError):
        Settings(_env_file=str(p))

    s = Settings(_env_file=str(p), _env_file_encoding='latin-1')
    assert s.model_dump() == {'pika': 'p!±@'}


test_default_env_file = """\
debug_mode=true
host=localhost
Port=8000
"""

test_prod_env_file = """\
debug_mode=false
host=https://example.com/services
"""


def test_multiple_env_file(tmp_path):
    base_env = tmp_path / '.env'
    base_env.write_text(test_default_env_file)
    prod_env = tmp_path / '.env.prod'
    prod_env.write_text(test_prod_env_file)

    class Settings(BaseSettings):
        debug_mode: bool
        host: str
        port: int

        model_config = SettingsConfigDict(env_file=[base_env, prod_env])

    s = Settings()
    assert s.debug_mode is False
    assert s.host == 'https://example.com/services'
    assert s.port == 8000


def test_model_env_file_override_model_config(tmp_path):
    base_env = tmp_path / '.env'
    base_env.write_text(test_default_env_file)
    prod_env = tmp_path / '.env.prod'
    prod_env.write_text(test_prod_env_file)

    class Settings(BaseSettings):
        debug_mode: bool
        host: str
        port: int

        model_config = SettingsConfigDict(env_file=prod_env)

    s = Settings(_env_file=base_env)
    assert s.debug_mode is True
    assert s.host == 'localhost'
    assert s.port == 8000


def test_multiple_env_file_encoding(tmp_path):
    base_env = tmp_path / '.env'
    base_env.write_text('pika=p!±@', encoding='latin-1')
    prod_env = tmp_path / '.env.prod'
    prod_env.write_text('pika=chu!±@', encoding='latin-1')

    class Settings(BaseSettings):
        pika: str

    s = Settings(_env_file=[base_env, prod_env], _env_file_encoding='latin-1')
    assert s.pika == 'chu!±@'


def test_read_dotenv_vars(tmp_path):
    base_env = tmp_path / '.env'
    base_env.write_text(test_default_env_file)
    prod_env = tmp_path / '.env.prod'
    prod_env.write_text(test_prod_env_file)

    source = DotEnvSettingsSource(
        BaseSettings(), env_file=[base_env, prod_env], env_file_encoding='utf8', case_sensitive=False
    )
    assert source._read_env_files() == {
        'debug_mode': 'false',
        'host': 'https://example.com/services',
        'port': '8000',
    }

    source = DotEnvSettingsSource(
        BaseSettings(), env_file=[base_env, prod_env], env_file_encoding='utf8', case_sensitive=True
    )
    assert source._read_env_files() == {
        'debug_mode': 'false',
        'host': 'https://example.com/services',
        'Port': '8000',
    }


def test_read_dotenv_vars_when_env_file_is_none():
    assert (
        DotEnvSettingsSource(
            BaseSettings(), env_file=None, env_file_encoding=None, case_sensitive=False
        )._read_env_files()
        == {}
    )


@pytest.mark.skipif(yaml, reason='PyYAML is installed')
def test_yaml_not_installed(tmp_path):
    p = tmp_path / '.env'
    p.write_text(
        """
    foobar: "Hello"
    """
    )

    class Settings(BaseSettings):
        foobar: str
        model_config = SettingsConfigDict(yaml_file=p)

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls),)

    with pytest.raises(ImportError, match=r'^PyYAML is not installed, run `pip install pydantic-settings\[yaml\]`$'):
        Settings()


def test_alias_set(env):
    class Settings(BaseSettings):
        foo: str = Field('default foo', validation_alias='foo_env')
        bar: str = 'bar default'

    assert Settings.model_fields['bar'].alias is None
    assert Settings.model_fields['bar'].validation_alias is None
    assert Settings.model_fields['foo'].alias is None
    assert Settings.model_fields['foo'].validation_alias == 'foo_env'

    class SubSettings(Settings):
        spam: str = 'spam default'

    assert SubSettings.model_fields['bar'].alias is None
    assert SubSettings.model_fields['bar'].validation_alias is None
    assert SubSettings.model_fields['foo'].alias is None
    assert SubSettings.model_fields['foo'].validation_alias == 'foo_env'

    assert SubSettings().model_dump() == {'foo': 'default foo', 'bar': 'bar default', 'spam': 'spam default'}
    env.set('foo_env', 'fff')
    assert SubSettings().model_dump() == {'foo': 'fff', 'bar': 'bar default', 'spam': 'spam default'}
    env.set('bar', 'bbb')
    assert SubSettings().model_dump() == {'foo': 'fff', 'bar': 'bbb', 'spam': 'spam default'}
    env.set('spam', 'sss')
    assert SubSettings().model_dump() == {'foo': 'fff', 'bar': 'bbb', 'spam': 'sss'}


def test_prefix_on_parent(env):
    class MyBaseSettings(BaseSettings):
        var: str = 'old'

    class MySubSettings(MyBaseSettings):
        model_config = SettingsConfigDict(env_prefix='PREFIX_')

    assert MyBaseSettings().model_dump() == {'var': 'old'}
    assert MySubSettings().model_dump() == {'var': 'old'}
    env.set('PREFIX_VAR', 'new')
    assert MyBaseSettings().model_dump() == {'var': 'old'}
    assert MySubSettings().model_dump() == {'var': 'new'}


def test_secrets_path(tmp_path):
    p = tmp_path / 'foo'
    p.write_text('foo_secret_value_str')

    class Settings(BaseSettings):
        foo: str

        model_config = SettingsConfigDict(secrets_dir=tmp_path)

    assert Settings().model_dump() == {'foo': 'foo_secret_value_str'}


def test_secrets_path_with_validation_alias(tmp_path):
    p = tmp_path / 'foo'
    p.write_text('{"bar": ["test"]}')

    class Settings(BaseSettings):
        foo: str = Field(validation_alias=AliasChoices(AliasPath('foo', 'bar', 0)))

        model_config = SettingsConfigDict(secrets_dir=tmp_path)

    assert Settings().model_dump() == {'foo': 'test'}


def test_secrets_case_sensitive(tmp_path):
    (tmp_path / 'SECRET_VAR').write_text('foo_env_value_str')

    class Settings(BaseSettings):
        secret_var: Optional[str] = None

        model_config = SettingsConfigDict(secrets_dir=tmp_path, case_sensitive=True)

    assert Settings().model_dump() == {'secret_var': None}


def test_secrets_case_insensitive(tmp_path):
    (tmp_path / 'SECRET_VAR').write_text('foo_env_value_str')

    class Settings(BaseSettings):
        secret_var: Optional[str]

        model_config = SettingsConfigDict(secrets_dir=tmp_path, case_sensitive=False)

    settings = Settings().model_dump()
    assert settings == {'secret_var': 'foo_env_value_str'}


def test_secrets_path_url(tmp_path):
    (tmp_path / 'foo').write_text('http://www.example.com')
    (tmp_path / 'bar').write_text('snap')

    class Settings(BaseSettings):
        foo: HttpUrl
        bar: SecretStr

        model_config = SettingsConfigDict(secrets_dir=tmp_path)

    settings = Settings()
    assert str(settings.foo) == 'http://www.example.com/'
    assert settings.bar == SecretStr('snap')


def test_secrets_path_json(tmp_path):
    p = tmp_path / 'foo'
    p.write_text('{"a": "b"}')

    class Settings(BaseSettings):
        foo: Dict[str, str]

        model_config = SettingsConfigDict(secrets_dir=tmp_path)

    assert Settings().model_dump() == {'foo': {'a': 'b'}}


def test_secrets_nested_optional_json(tmp_path):
    p = tmp_path / 'foo'
    p.write_text('{"a": 10}')

    class Foo(BaseModel):
        a: int

    class Settings(BaseSettings):
        foo: Optional[Foo] = None

        model_config = SettingsConfigDict(secrets_dir=tmp_path)

    assert Settings().model_dump() == {'foo': {'a': 10}}


def test_secrets_path_invalid_json(tmp_path):
    p = tmp_path / 'foo'
    p.write_text('{"a": "b"')

    class Settings(BaseSettings):
        foo: Dict[str, str]

        model_config = SettingsConfigDict(secrets_dir=tmp_path)

    with pytest.raises(SettingsError, match='error parsing value for field "foo" from source "SecretsSettingsSource"'):
        Settings()


def test_secrets_missing(tmp_path):
    class Settings(BaseSettings):
        foo: str
        bar: List[str]

        model_config = SettingsConfigDict(secrets_dir=tmp_path)

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert exc_info.value.errors(include_url=False) == [
        {'type': 'missing', 'loc': ('foo',), 'msg': 'Field required', 'input': {}},
        {'input': {}, 'loc': ('bar',), 'msg': 'Field required', 'type': 'missing'},
    ]


def test_secrets_invalid_secrets_dir(tmp_path):
    p1 = tmp_path / 'foo'
    p1.write_text('foo_secret_value_str')

    class Settings(BaseSettings):
        foo: str

        model_config = SettingsConfigDict(secrets_dir=p1)

    with pytest.raises(SettingsError, match='secrets_dir must reference a directory, not a file'):
        Settings()


@pytest.mark.skipif(sys.platform.startswith('win'), reason='windows paths break regex')
def test_secrets_missing_location(tmp_path):
    class Settings(BaseSettings):
        model_config = SettingsConfigDict(secrets_dir=tmp_path / 'does_not_exist')

    with pytest.warns(UserWarning, match=f'directory "{tmp_path}/does_not_exist" does not exist'):
        Settings()


@pytest.mark.skipif(sys.platform.startswith('win'), reason='windows paths break regex')
def test_secrets_file_is_a_directory(tmp_path):
    p1 = tmp_path / 'foo'
    p1.mkdir()

    class Settings(BaseSettings):
        foo: Optional[str] = None

        model_config = SettingsConfigDict(secrets_dir=tmp_path)

    with pytest.warns(UserWarning, match=f'attempted to load secret file "{tmp_path}/foo" but found a directory inste'):
        Settings()


def test_secrets_dotenv_precedence(tmp_path):
    s = tmp_path / 'foo'
    s.write_text('foo_secret_value_str')

    e = tmp_path / '.env'
    e.write_text('foo=foo_env_value_str')

    class Settings(BaseSettings):
        foo: str

        model_config = SettingsConfigDict(secrets_dir=tmp_path)

    assert Settings(_env_file=e).model_dump() == {'foo': 'foo_env_value_str'}


def test_external_settings_sources_precedence(env):
    def external_source_0() -> Dict[str, str]:
        return {'apple': 'value 0', 'banana': 'value 2'}

    def external_source_1() -> Dict[str, str]:
        return {'apple': 'value 1', 'raspberry': 'value 3'}

    class Settings(BaseSettings):
        apple: str
        banana: str
        raspberry: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (
                init_settings,
                env_settings,
                dotenv_settings,
                file_secret_settings,
                external_source_0,
                external_source_1,
            )

    env.set('banana', 'value 1')
    assert Settings().model_dump() == {'apple': 'value 0', 'banana': 'value 1', 'raspberry': 'value 3'}


def test_external_settings_sources_filter_env_vars():
    vault_storage = {'user:password': {'apple': 'value 0', 'banana': 'value 2'}}

    class VaultSettingsSource(PydanticBaseSettingsSource):
        def __init__(self, settings_cls: Type[BaseSettings], user: str, password: str):
            self.user = user
            self.password = password
            super().__init__(settings_cls)

        def get_field_value(self, field: FieldInfo, field_name: str) -> Any:
            pass

        def __call__(self) -> Dict[str, str]:
            vault_vars = vault_storage[f'{self.user}:{self.password}']
            return {
                field_name: vault_vars[field_name]
                for field_name in self.settings_cls.model_fields.keys()
                if field_name in vault_vars
            }

    class Settings(BaseSettings):
        apple: str
        banana: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (
                init_settings,
                env_settings,
                dotenv_settings,
                file_secret_settings,
                VaultSettingsSource(settings_cls, user='user', password='password'),
            )

    assert Settings().model_dump() == {'apple': 'value 0', 'banana': 'value 2'}


def test_customise_sources_empty():
    class Settings(BaseSettings):
        apple: str = 'default'
        banana: str = 'default'

        @classmethod
        def settings_customise_sources(cls, *args, **kwargs):
            return ()

    assert Settings().model_dump() == {'apple': 'default', 'banana': 'default'}
    assert Settings(apple='xxx').model_dump() == {'apple': 'default', 'banana': 'default'}


def test_builtins_settings_source_repr():
    assert (
        repr(InitSettingsSource(BaseSettings, init_kwargs={'apple': 'value 0', 'banana': 'value 1'}))
        == "InitSettingsSource(init_kwargs={'apple': 'value 0', 'banana': 'value 1'})"
    )
    assert (
        repr(EnvSettingsSource(BaseSettings, env_nested_delimiter='__'))
        == "EnvSettingsSource(env_nested_delimiter='__', env_prefix_len=0)"
    )
    assert repr(DotEnvSettingsSource(BaseSettings, env_file='.env', env_file_encoding='utf-8')) == (
        "DotEnvSettingsSource(env_file='.env', env_file_encoding='utf-8', "
        'env_nested_delimiter=None, env_prefix_len=0)'
    )
    assert (
        repr(SecretsSettingsSource(BaseSettings, secrets_dir='/secrets'))
        == "SecretsSettingsSource(secrets_dir='/secrets')"
    )


def _parse_custom_dict(value: str) -> Callable[[str], Dict[int, str]]:
    """A custom parsing function passed into env parsing test."""
    res = {}
    for part in value.split(','):
        k, v = part.split('=')
        res[int(k)] = v
    return res


class CustomEnvSettingsSource(EnvSettingsSource):
    def prepare_field_value(self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool) -> Any:
        if not value:
            return None

        return _parse_custom_dict(value)


def test_env_setting_source_custom_env_parse(env):
    class Settings(BaseSettings):
        top: Dict[int, str]

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (CustomEnvSettingsSource(settings_cls),)

    with pytest.raises(ValidationError):
        Settings()
    env.set('top', '1=apple,2=banana')
    s = Settings()
    assert s.top == {1: 'apple', 2: 'banana'}


class BadCustomEnvSettingsSource(EnvSettingsSource):
    def prepare_field_value(self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool) -> Any:
        """A custom parsing function passed into env parsing test."""
        return int(value)


def test_env_settings_source_custom_env_parse_is_bad(env):
    class Settings(BaseSettings):
        top: Dict[int, str]

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (BadCustomEnvSettingsSource(settings_cls),)

    env.set('top', '1=apple,2=banana')
    with pytest.raises(
        SettingsError, match='error parsing value for field "top" from source "BadCustomEnvSettingsSource"'
    ):
        Settings()


class CustomSecretsSettingsSource(SecretsSettingsSource):
    def prepare_field_value(self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool) -> Any:
        if not value:
            return None

        return _parse_custom_dict(value)


def test_secret_settings_source_custom_env_parse(tmp_path):
    p = tmp_path / 'top'
    p.write_text('1=apple,2=banana')

    class Settings(BaseSettings):
        top: Dict[int, str]

        model_config = SettingsConfigDict(secrets_dir=tmp_path)

        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (CustomSecretsSettingsSource(settings_cls, tmp_path),)

    s = Settings()
    assert s.top == {1: 'apple', 2: 'banana'}


class BadCustomSettingsSource(EnvSettingsSource):
    def get_field_value(self, field: FieldInfo, field_name: str) -> Any:
        raise ValueError('Error')


def test_custom_source_get_field_value_error(env):
    class Settings(BaseSettings):
        top: Dict[int, str]

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (BadCustomSettingsSource(settings_cls),)

    with pytest.raises(
        SettingsError, match='error getting value for field "top" from source "BadCustomSettingsSource"'
    ):
        Settings()


def test_nested_env_complex_values(env):
    class SubSubModel(BaseSettings):
        dvals: Dict

    class SubModel(BaseSettings):
        vals: List[str]
        sub_sub_model: SubSubModel

    class Cfg(BaseSettings):
        sub_model: SubModel

        model_config = SettingsConfigDict(env_prefix='cfg_', env_nested_delimiter='__')

    env.set('cfg_sub_model__vals', '["one", "two"]')
    env.set('cfg_sub_model__sub_sub_model__dvals', '{"three": 4}')

    assert Cfg().model_dump() == {'sub_model': {'vals': ['one', 'two'], 'sub_sub_model': {'dvals': {'three': 4}}}}

    env.set('cfg_sub_model__vals', 'invalid')
    with pytest.raises(
        SettingsError, match='error parsing value for field "sub_model" from source "EnvSettingsSource"'
    ):
        Cfg()


def test_nested_env_nonexisting_field(env):
    class SubModel(BaseSettings):
        vals: List[str]

    class Cfg(BaseSettings):
        sub_model: SubModel

        model_config = SettingsConfigDict(env_prefix='cfg_', env_nested_delimiter='__')

    env.set('cfg_sub_model__foo_vals', '[]')
    with pytest.raises(ValidationError):
        Cfg()


def test_nested_env_nonexisting_field_deep(env):
    class SubModel(BaseSettings):
        vals: List[str]

    class Cfg(BaseSettings):
        sub_model: SubModel

        model_config = SettingsConfigDict(env_prefix='cfg_', env_nested_delimiter='__')

    env.set('cfg_sub_model__vals__foo__bar__vals', '[]')
    with pytest.raises(ValidationError):
        Cfg()


def test_nested_env_union_complex_values(env):
    class SubModel(BaseSettings):
        vals: Union[List[str], Dict[str, str]]

    class Cfg(BaseSettings):
        sub_model: SubModel

        model_config = SettingsConfigDict(env_prefix='cfg_', env_nested_delimiter='__')

    env.set('cfg_sub_model__vals', '["one", "two"]')
    assert Cfg().model_dump() == {'sub_model': {'vals': ['one', 'two']}}

    env.set('cfg_sub_model__vals', '{"three": "four"}')
    assert Cfg().model_dump() == {'sub_model': {'vals': {'three': 'four'}}}

    env.set('cfg_sub_model__vals', 'stringval')
    with pytest.raises(ValidationError):
        Cfg()

    env.set('cfg_sub_model__vals', '{"invalid": dict}')
    with pytest.raises(ValidationError):
        Cfg()


def test_discriminated_union_with_callable_discriminator(env):
    class A(BaseModel):
        x: Literal['a'] = 'a'
        y: str

    class B(BaseModel):
        x: Literal['b'] = 'b'
        z: str

    def get_discriminator_value(v: Any) -> Hashable:
        if isinstance(v, dict):
            v0 = v.get('x')
        else:
            v0 = getattr(v, 'x', None)

        if v0 == 'a':
            return 'a'
        elif v0 == 'b':
            return 'b'
        else:
            return None

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_nested_delimiter='__')

        # Discriminated union using a callable discriminator.
        a_or_b: Annotated[Union[Annotated[A, Tag('a')], Annotated[B, Tag('b')]], Discriminator(get_discriminator_value)]

    # Set up environment so that the discriminator is 'a'.
    env.set('a_or_b__x', 'a')
    env.set('a_or_b__y', 'foo')

    s = Settings()

    assert s.a_or_b.x == 'a'
    assert s.a_or_b.y == 'foo'


def test_nested_model_case_insensitive(env):
    class SubSubSub(BaseModel):
        VaL3: str
        val4: str = Field(validation_alias='VAL4')

    class SubSub(BaseModel):
        Val2: str
        SUB_sub_SuB: SubSubSub

    class Sub(BaseModel):
        VAL1: str
        SUB_sub: SubSub

    class Settings(BaseSettings):
        nested: Sub

        model_config = SettingsConfigDict(env_nested_delimiter='__')

    env.set('nested', '{"val1": "v1", "sub_SUB": {"VAL2": "v2", "sub_SUB_sUb": {"vAl3": "v3", "VAL4": "v4"}}}')
    s = Settings()
    assert s.nested.VAL1 == 'v1'
    assert s.nested.SUB_sub.Val2 == 'v2'
    assert s.nested.SUB_sub.SUB_sub_SuB.VaL3 == 'v3'
    assert s.nested.SUB_sub.SUB_sub_SuB.val4 == 'v4'


def test_dotenv_extra_allow(tmp_path):
    p = tmp_path / '.env'
    p.write_text('a=b\nx=y')

    class Settings(BaseSettings):
        a: str

        model_config = SettingsConfigDict(env_file=p, extra='allow')

    s = Settings()
    assert s.a == 'b'
    assert s.x == 'y'


def test_dotenv_extra_forbid(tmp_path):
    p = tmp_path / '.env'
    p.write_text('a=b\nx=y')

    class Settings(BaseSettings):
        a: str

        model_config = SettingsConfigDict(env_file=p, extra='forbid')

    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert exc_info.value.errors(include_url=False) == [
        {'type': 'extra_forbidden', 'loc': ('x',), 'msg': 'Extra inputs are not permitted', 'input': 'y'}
    ]


def test_dotenv_extra_case_insensitive(tmp_path):
    p = tmp_path / '.env'
    p.write_text('a=b')

    class Settings(BaseSettings):
        A: str

        model_config = SettingsConfigDict(env_file=p, extra='forbid')

    s = Settings()
    assert s.A == 'b'


def test_dotenv_extra_sub_model_case_insensitive(tmp_path):
    p = tmp_path / '.env'
    p.write_text('a=b\nSUB_model={"v": "v1"}')

    class SubModel(BaseModel):
        v: str

    class Settings(BaseSettings):
        A: str
        sub_MODEL: SubModel

        model_config = SettingsConfigDict(env_file=p, extra='forbid')

    s = Settings()
    assert s.A == 'b'
    assert s.sub_MODEL.v == 'v1'


def test_nested_bytes_field(env):
    class SubModel(BaseModel):
        v1: str
        v2: bytes

    class Settings(BaseSettings):
        v0: str
        sub_model: SubModel

        model_config = SettingsConfigDict(env_nested_delimiter='__', env_prefix='TEST_')

    env.set('TEST_V0', 'v0')
    env.set('TEST_SUB_MODEL__V1', 'v1')
    env.set('TEST_SUB_MODEL__V2', 'v2')

    s = Settings()

    assert s.v0 == 'v0'
    assert s.sub_model.v1 == 'v1'
    assert s.sub_model.v2 == b'v2'


def test_protected_namespace_defaults():
    # pydantic default
    with pytest.warns(UserWarning, match='Field "model_prefixed_field" has conflict with protected namespace "model_"'):

        class Model(BaseSettings):
            model_prefixed_field: str

    # pydantic-settings default
    with pytest.raises(
        UserWarning, match='Field "settings_prefixed_field" has conflict with protected namespace "settings_"'
    ):

        class Model1(BaseSettings):
            settings_prefixed_field: str

    with pytest.raises(
        NameError,
        match=(
            'Field "settings_customise_sources" conflicts with member <bound method '
            "BaseSettings.settings_customise_sources of <class 'pydantic_settings.main.BaseSettings'>> "
            'of protected namespace "settings_".'
        ),
    ):

        class Model2(BaseSettings):
            settings_customise_sources: str


def test_case_sensitive_from_args(monkeypatch):
    class Settings(BaseSettings):
        foo: str

    # Need to patch os.environ to get build to work on Windows, where os.environ is case insensitive
    monkeypatch.setattr(os, 'environ', value={'Foo': 'foo'})
    with pytest.raises(ValidationError) as exc_info:
        Settings(_case_sensitive=True)
    assert exc_info.value.errors(include_url=False) == [
        {'type': 'missing', 'loc': ('foo',), 'msg': 'Field required', 'input': {}}
    ]


def test_env_prefix_from_args(env):
    class Settings(BaseSettings):
        apple: str

    env.set('foobar_apple', 'has_prefix')
    s = Settings(_env_prefix='foobar_')
    assert s.apple == 'has_prefix'


def test_env_json_field(env):
    class Settings(BaseSettings):
        x: Json

    env.set('x', '{"foo": "bar"}')

    s = Settings()
    assert s.x == {'foo': 'bar'}

    env.set('x', 'test')
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert exc_info.value.errors(include_url=False) == [
        {
            'type': 'json_invalid',
            'loc': ('x',),
            'msg': 'Invalid JSON: expected ident at line 1 column 2',
            'input': 'test',
            'ctx': {'error': 'expected ident at line 1 column 2'},
        }
    ]


def test_env_parse_enums(env):
    class Settings(BaseSettings):
        fruit: FruitsEnum

    with pytest.raises(ValidationError) as exc_info:
        env.set('FRUIT', 'kiwi')
        s = Settings()
    assert exc_info.value.errors(include_url=False) == [
        {
            'type': 'enum',
            'loc': ('fruit',),
            'msg': 'Input should be 0, 1 or 2',
            'input': 'kiwi',
            'ctx': {'expected': '0, 1 or 2'},
        }
    ]

    env.set('FRUIT', str(FruitsEnum.lime.value))
    s = Settings()
    assert s.fruit == FruitsEnum.lime

    env.set('FRUIT', 'kiwi')
    s = Settings(_env_parse_enums=True)
    assert s.fruit == FruitsEnum.kiwi

    env.set('FRUIT', str(FruitsEnum.lime.value))
    s = Settings(_env_parse_enums=True)
    assert s.fruit == FruitsEnum.lime


def test_env_parse_none_str(env):
    env.set('x', 'null')
    env.set('y', 'y_override')

    class Settings(BaseSettings):
        x: Optional[str] = 'x_default'
        y: Optional[str] = 'y_default'

    s = Settings()
    assert s.x == 'null'
    assert s.y == 'y_override'
    s = Settings(_env_parse_none_str='null')
    assert s.x is None
    assert s.y == 'y_override'

    env.set('nested__x', 'None')
    env.set('nested__y', 'y_override')
    env.set('nested__deep__z', 'None')

    class NestedBaseModel(BaseModel):
        x: Optional[str] = 'x_default'
        y: Optional[str] = 'y_default'
        deep: Optional[dict] = {'z': 'z_default'}
        keep: Optional[dict] = {'z': 'None'}

    class NestedSettings(BaseSettings, env_nested_delimiter='__'):
        nested: Optional[NestedBaseModel] = NestedBaseModel()

    s = NestedSettings()
    assert s.nested.x == 'None'
    assert s.nested.y == 'y_override'
    assert s.nested.deep['z'] == 'None'
    assert s.nested.keep['z'] == 'None'
    s = NestedSettings(_env_parse_none_str='None')
    assert s.nested.x is None
    assert s.nested.y == 'y_override'
    assert s.nested.deep['z'] is None
    assert s.nested.keep['z'] == 'None'

    env.set('nested__deep', 'None')

    with pytest.raises(ValidationError):
        s = NestedSettings()
    s = NestedSettings(_env_parse_none_str='None')
    assert s.nested.x is None
    assert s.nested.y == 'y_override'
    assert s.nested.deep['z'] is None
    assert s.nested.keep['z'] == 'None'

    env.pop('nested__deep__z')

    with pytest.raises(ValidationError):
        s = NestedSettings()
    s = NestedSettings(_env_parse_none_str='None')
    assert s.nested.x is None
    assert s.nested.y == 'y_override'
    assert s.nested.deep is None
    assert s.nested.keep['z'] == 'None'


def test_env_json_field_dict(env):
    class Settings(BaseSettings):
        x: Json[Dict[str, int]]

    env.set('x', '{"foo": 1}')

    s = Settings()
    assert s.x == {'foo': 1}

    env.set('x', '{"foo": "bar"}')
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert exc_info.value.errors(include_url=False) == [
        {
            'type': 'int_parsing',
            'loc': ('x', 'foo'),
            'msg': 'Input should be a valid integer, unable to parse string as an integer',
            'input': 'bar',
        }
    ]


def test_custom_env_source_default_values_from_config():
    class CustomEnvSettingsSource(EnvSettingsSource):
        pass

    class Settings(BaseSettings):
        foo: str = 'test'

        model_config = SettingsConfigDict(env_prefix='prefix_', case_sensitive=True)

    s = Settings()
    assert s.model_config['env_prefix'] == 'prefix_'
    assert s.model_config['case_sensitive'] is True

    c = CustomEnvSettingsSource(Settings)
    assert c.env_prefix == 'prefix_'
    assert c.case_sensitive is True


def test_model_config_through_class_kwargs(env):
    class Settings(BaseSettings, env_prefix='foobar_', title='Test Settings Model'):
        apple: str

    assert Settings.model_config['title'] == 'Test Settings Model'  # pydantic config
    assert Settings.model_config['env_prefix'] == 'foobar_'  # pydantic-settings config

    assert Settings.model_json_schema()['title'] == 'Test Settings Model'

    env.set('foobar_apple', 'has_prefix')
    s = Settings()
    assert s.apple == 'has_prefix'


def test_root_model_as_field(env):
    class Foo(BaseModel):
        x: int
        y: Dict[str, int]

    FooRoot = RootModel[List[Foo]]

    class Settings(BaseSettings):
        z: FooRoot

    env.set('z', '[{"x": 1, "y": {"foo": 1}}, {"x": 2, "y": {"foo": 2}}]')
    s = Settings()
    assert s.model_dump() == {'z': [{'x': 1, 'y': {'foo': 1}}, {'x': 2, 'y': {'foo': 2}}]}


def test_optional_field_from_env(env):
    class Settings(BaseSettings):
        x: Optional[str] = None

    env.set('x', '123')

    s = Settings()
    assert s.x == '123'


def test_dotenv_optional_json_field(tmp_path):
    p = tmp_path / '.env'
    p.write_text("""DATA='{"foo":"bar"}'""")

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_file=p)

        data: Optional[Json[Dict[str, str]]] = Field(default=None)

    s = Settings()
    assert s.data == {'foo': 'bar'}


def test_cli_nested_arg():
    class SubSubValue(BaseModel):
        v6: str

    class SubValue(BaseModel):
        v4: str
        v5: int
        sub_sub: SubSubValue

    class TopValue(BaseModel):
        v1: str
        v2: str
        v3: str
        sub: SubValue

    class Cfg(BaseSettings):
        v0: str
        v0_union: Union[SubValue, int]
        top: TopValue

    args: List[str] = []
    args += ['--top', '{"v1": "json-1", "v2": "json-2", "sub": {"v5": "xx"}}']
    args += ['--top.sub.v5', '5']
    args += ['--v0', '0']
    args += ['--top.v2', '2']
    args += ['--top.v3', '3']
    args += ['--v0_union', '0']
    args += ['--top.sub.sub_sub.v6', '6']
    args += ['--top.sub.v4', '4']
    cfg = Cfg(_cli_parse_args=args)
    assert cfg.model_dump() == {
        'v0': '0',
        'v0_union': 0,
        'top': {
            'v1': 'json-1',
            'v2': '2',
            'v3': '3',
            'sub': {'v4': '4', 'v5': 5, 'sub_sub': {'v6': '6'}},
        },
    }


def test_cli_source_prioritization(env):
    class CfgDefault(BaseSettings):
        foo: str

    class CfgPrioritized(BaseSettings):
        foo: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return env_settings, CliSettingsSource(settings_cls, cli_parse_args=['--foo', 'FOO FROM CLI'])

    env.set('FOO', 'FOO FROM ENV')

    cfg = CfgDefault(_cli_parse_args=['--foo', 'FOO FROM CLI'])
    assert cfg.model_dump() == {'foo': 'FOO FROM CLI'}

    cfg = CfgPrioritized()
    assert cfg.model_dump() == {'foo': 'FOO FROM ENV'}


def test_cli_alias_arg():
    class Animal(BaseModel):
        name: str

    class Cfg(BaseSettings):
        apple: str = Field(alias='alias')
        pet: Animal = Field(alias='critter')

    cfg = Cfg(_cli_parse_args=['--alias', 'foo', '--critter.name', 'harry'])
    assert cfg.model_dump() == {'apple': 'foo', 'pet': {'name': 'harry'}}
    assert cfg.model_dump(by_alias=True) == {'alias': 'foo', 'critter': {'name': 'harry'}}


def test_cli_case_insensitve_arg():
    class Cfg(BaseSettings):
        Foo: str
        Bar: str

    cfg = Cfg(_cli_parse_args=['--FOO=--VAL', '--BAR', '"--VAL"'])
    assert cfg.model_dump() == {'Foo': '--VAL', 'Bar': '"--VAL"'}

    cfg = Cfg(_cli_parse_args=['--Foo=--VAL', '--Bar', '"--VAL"'], _case_sensitive=True)
    assert cfg.model_dump() == {'Foo': '--VAL', 'Bar': '"--VAL"'}

    with pytest.raises(SystemExit):
        Cfg(_cli_parse_args=['--FOO=--VAL', '--BAR', '"--VAL"'], _case_sensitive=True)

    with pytest.raises(SettingsError) as exc_info:
        CliSettingsSource(Cfg, root_parser=CliDummyParser(), case_sensitive=False)
    assert str(exc_info.value) == 'Case-insensitive matching is only supported on the internal root parser'


def test_cli_help_differentiation(capsys, monkeypatch):
    class Cfg(BaseSettings):
        foo: str
        bar: int = 123
        boo: int = Field(default_factory=lambda: 456)

    argparse_options_text = 'options' if sys.version_info >= (3, 10) else 'optional arguments'

    with monkeypatch.context() as m:
        m.setattr(sys, 'argv', ['example.py', '--help'])

        with pytest.raises(SystemExit):
            Cfg(_cli_parse_args=True)

        assert (
            re.sub(r'0x\w+', '0xffffffff', capsys.readouterr().out, re.MULTILINE)
            == f"""usage: example.py [-h] [--foo str] [--bar int] [--boo int]

{argparse_options_text}:
  -h, --help  show this help message and exit
  --foo str   (required)
  --bar int   (default: 123)
  --boo int   (default: <function
              test_cli_help_differentiation.<locals>.Cfg.<lambda> at
              0xffffffff>)
"""
        )


def test_cli_help_string_format(capsys, monkeypatch):
    class Cfg(BaseSettings):
        date_str: str = '%Y-%m-%d'

    argparse_options_text = 'options' if sys.version_info >= (3, 10) else 'optional arguments'

    with monkeypatch.context() as m:
        m.setattr(sys, 'argv', ['example.py', '--help'])

        with pytest.raises(SystemExit):
            Cfg(_cli_parse_args=True)

        assert (
            re.sub(r'0x\w+', '0xffffffff', capsys.readouterr().out, re.MULTILINE)
            == f"""usage: example.py [-h] [--date_str str]

{argparse_options_text}:
  -h, --help      show this help message and exit
  --date_str str  (default: %Y-%m-%d)
"""
        )


def test_cli_nested_dataclass_arg():
    @pydantic_dataclasses.dataclass
    class MyDataclass:
        foo: int
        bar: str

    class Settings(BaseSettings):
        n: MyDataclass

    s = Settings(_cli_parse_args=['--n.foo', '123', '--n.bar', 'bar value'])
    assert isinstance(s.n, MyDataclass)
    assert s.n.foo == 123
    assert s.n.bar == 'bar value'


@pytest.mark.parametrize('prefix', ['', 'child.'])
def test_cli_list_arg(prefix):
    class Obj(BaseModel):
        val: int

    class Child(BaseModel):
        num_list: Optional[List[int]] = None
        obj_list: Optional[List[Obj]] = None
        str_list: Optional[List[str]] = None
        union_list: Optional[List[Union[Obj, int]]] = None

    class Cfg(BaseSettings):
        num_list: Optional[List[int]] = None
        obj_list: Optional[List[Obj]] = None
        union_list: Optional[List[Union[Obj, int]]] = None
        str_list: Optional[List[str]] = None
        child: Optional[Child] = None

    def check_answer(cfg, prefix, expected):
        if prefix:
            assert cfg.model_dump() == {
                'num_list': None,
                'obj_list': None,
                'union_list': None,
                'str_list': None,
                'child': expected,
            }
        else:
            expected['child'] = None
            assert cfg.model_dump() == expected

    args: List[str] = []
    args = [f'--{prefix}num_list', '[1,2]']
    args += [f'--{prefix}num_list', '3,4']
    args += [f'--{prefix}num_list', '5', f'--{prefix}num_list', '6']
    cfg = Cfg(_cli_parse_args=args)
    expected = {
        'num_list': [1, 2, 3, 4, 5, 6],
        'obj_list': None,
        'union_list': None,
        'str_list': None,
    }
    check_answer(cfg, prefix, expected)

    args = [f'--{prefix}obj_list', '[{"val":1},{"val":2}]']
    args += [f'--{prefix}obj_list', '{"val":3},{"val":4}']
    args += [f'--{prefix}obj_list', '{"val":5}', f'--{prefix}obj_list', '{"val":6}']
    cfg = Cfg(_cli_parse_args=args)
    expected = {
        'num_list': None,
        'obj_list': [{'val': 1}, {'val': 2}, {'val': 3}, {'val': 4}, {'val': 5}, {'val': 6}],
        'union_list': None,
        'str_list': None,
    }
    check_answer(cfg, prefix, expected)

    args = [f'--{prefix}union_list', '[{"val":1},2]', f'--{prefix}union_list', '[3,{"val":4}]']
    args += [f'--{prefix}union_list', '{"val":5},6', f'--{prefix}union_list', '7,{"val":8}']
    args += [f'--{prefix}union_list', '{"val":9}', f'--{prefix}union_list', '10']
    cfg = Cfg(_cli_parse_args=args)
    expected = {
        'num_list': None,
        'obj_list': None,
        'union_list': [{'val': 1}, 2, 3, {'val': 4}, {'val': 5}, 6, 7, {'val': 8}, {'val': 9}, 10],
        'str_list': None,
    }
    check_answer(cfg, prefix, expected)

    args = [f'--{prefix}str_list', '["0,0","1,1"]']
    args += [f'--{prefix}str_list', '"2,2","3,3"']
    args += [f'--{prefix}str_list', '"4,4"', f'--{prefix}str_list', '"5,5"']
    cfg = Cfg(_cli_parse_args=args)
    expected = {
        'num_list': None,
        'obj_list': None,
        'union_list': None,
        'str_list': ['0,0', '1,1', '2,2', '3,3', '4,4', '5,5'],
    }
    check_answer(cfg, prefix, expected)


def test_cli_list_json_value_parsing():
    class Cfg(BaseSettings):
        json_list: List[Union[str, bool, None]]

    assert Cfg(
        _cli_parse_args=[
            '--json_list',
            'true,"true"',
            '--json_list',
            'false,"false"',
            '--json_list',
            'null,"null"',
            '--json_list',
            'hi,"bye"',
        ]
    ).model_dump() == {'json_list': [True, 'true', False, 'false', None, 'null', 'hi', 'bye']}

    assert Cfg(_cli_parse_args=['--json_list', '"","","",""']).model_dump() == {'json_list': ['', '', '', '']}
    assert Cfg(_cli_parse_args=['--json_list', ',,,']).model_dump() == {'json_list': ['', '', '', '']}


@pytest.mark.parametrize('prefix', ['', 'child.'])
def test_cli_dict_arg(prefix):
    class Child(BaseModel):
        check_dict: Dict[str, str]

    class Cfg(BaseSettings):
        check_dict: Optional[Dict[str, str]] = None
        child: Optional[Child] = None

    args: List[str] = []
    args = [f'--{prefix}check_dict', '{"k1":"a","k2":"b"}']
    args += [f'--{prefix}check_dict', '{"k3":"c"},{"k4":"d"}']
    args += [f'--{prefix}check_dict', '{"k5":"e"}', f'--{prefix}check_dict', '{"k6":"f"}']
    args += [f'--{prefix}check_dict', '[k7=g,k8=h]']
    args += [f'--{prefix}check_dict', 'k9=i,k10=j']
    args += [f'--{prefix}check_dict', 'k11=k', f'--{prefix}check_dict', 'k12=l']
    args += [f'--{prefix}check_dict', '[{"k13":"m"},k14=n]', f'--{prefix}check_dict', '[k15=o,{"k16":"p"}]']
    args += [f'--{prefix}check_dict', '{"k17":"q"},k18=r', f'--{prefix}check_dict', 'k19=s,{"k20":"t"}']
    args += [f'--{prefix}check_dict', '{"k21":"u"},k22=v,{"k23":"w"}']
    args += [f'--{prefix}check_dict', 'k24=x,{"k25":"y"},k26=z']
    args += [f'--{prefix}check_dict', '[k27="x,y",k28="x,y"]']
    args += [f'--{prefix}check_dict', 'k29="x,y",k30="x,y"']
    args += [f'--{prefix}check_dict', 'k31="x,y"', f'--{prefix}check_dict', 'k32="x,y"']
    cfg = Cfg(_cli_parse_args=args)
    expected: Dict[str, Any] = {
        'check_dict': {
            'k1': 'a',
            'k2': 'b',
            'k3': 'c',
            'k4': 'd',
            'k5': 'e',
            'k6': 'f',
            'k7': 'g',
            'k8': 'h',
            'k9': 'i',
            'k10': 'j',
            'k11': 'k',
            'k12': 'l',
            'k13': 'm',
            'k14': 'n',
            'k15': 'o',
            'k16': 'p',
            'k17': 'q',
            'k18': 'r',
            'k19': 's',
            'k20': 't',
            'k21': 'u',
            'k22': 'v',
            'k23': 'w',
            'k24': 'x',
            'k25': 'y',
            'k26': 'z',
            'k27': 'x,y',
            'k28': 'x,y',
            'k29': 'x,y',
            'k30': 'x,y',
            'k31': 'x,y',
            'k32': 'x,y',
        }
    }
    if prefix:
        expected = {'check_dict': None, 'child': expected}
    else:
        expected['child'] = None
    assert cfg.model_dump() == expected

    with pytest.raises(SettingsError) as exc_info:
        cfg = Cfg(_cli_parse_args=[f'--{prefix}check_dict', 'k9="i'])
    assert str(exc_info.value) == f'Parsing error encountered for {prefix}check_dict: Mismatched quotes'

    with pytest.raises(SettingsError):
        cfg = Cfg(_cli_parse_args=[f'--{prefix}check_dict', 'k9=i"'])
    assert str(exc_info.value) == f'Parsing error encountered for {prefix}check_dict: Mismatched quotes'


def test_cli_union_dict_arg():
    class Cfg(BaseSettings):
        union_str_dict: Union[str, Dict[str, Any]]

    with pytest.raises(ValidationError) as exc_info:
        args = ['--union_str_dict', 'hello world', '--union_str_dict', 'hello world']
        cfg = Cfg(_cli_parse_args=args)
    assert exc_info.value.errors(include_url=False) == [
        {
            'input': [
                'hello world',
                'hello world',
            ],
            'loc': (
                'union_str_dict',
                'str',
            ),
            'msg': 'Input should be a valid string',
            'type': 'string_type',
        },
        {
            'input': [
                'hello world',
                'hello world',
            ],
            'loc': (
                'union_str_dict',
                'dict[str,any]',
            ),
            'msg': 'Input should be a valid dictionary',
            'type': 'dict_type',
        },
    ]

    args = ['--union_str_dict', 'hello world']
    cfg = Cfg(_cli_parse_args=args)
    assert cfg.model_dump() == {'union_str_dict': 'hello world'}

    args = ['--union_str_dict', '{"hello": "world"}']
    cfg = Cfg(_cli_parse_args=args)
    assert cfg.model_dump() == {'union_str_dict': {'hello': 'world'}}

    args = ['--union_str_dict', 'hello=world']
    cfg = Cfg(_cli_parse_args=args)
    assert cfg.model_dump() == {'union_str_dict': {'hello': 'world'}}

    args = ['--union_str_dict', '"hello=world"']
    cfg = Cfg(_cli_parse_args=args)
    assert cfg.model_dump() == {'union_str_dict': 'hello=world'}

    class Cfg(BaseSettings):
        union_list_dict: Union[List[str], Dict[str, Any]]

    with pytest.raises(ValidationError) as exc_info:
        args = ['--union_list_dict', 'hello,world']
        cfg = Cfg(_cli_parse_args=args)
    assert exc_info.value.errors(include_url=False) == [
        {
            'input': 'hello,world',
            'loc': (
                'union_list_dict',
                'list[str]',
            ),
            'msg': 'Input should be a valid list',
            'type': 'list_type',
        },
        {
            'input': 'hello,world',
            'loc': (
                'union_list_dict',
                'dict[str,any]',
            ),
            'msg': 'Input should be a valid dictionary',
            'type': 'dict_type',
        },
    ]

    args = ['--union_list_dict', 'hello,world', '--union_list_dict', 'hello,world']
    cfg = Cfg(_cli_parse_args=args)
    assert cfg.model_dump() == {'union_list_dict': ['hello', 'world', 'hello', 'world']}

    args = ['--union_list_dict', '[hello,world]']
    cfg = Cfg(_cli_parse_args=args)
    assert cfg.model_dump() == {'union_list_dict': ['hello', 'world']}

    args = ['--union_list_dict', '{"hello": "world"}']
    cfg = Cfg(_cli_parse_args=args)
    assert cfg.model_dump() == {'union_list_dict': {'hello': 'world'}}

    args = ['--union_list_dict', 'hello=world']
    cfg = Cfg(_cli_parse_args=args)
    assert cfg.model_dump() == {'union_list_dict': {'hello': 'world'}}

    with pytest.raises(ValidationError) as exc_info:
        args = ['--union_list_dict', '"hello=world"']
        cfg = Cfg(_cli_parse_args=args)
    assert exc_info.value.errors(include_url=False) == [
        {
            'input': 'hello=world',
            'loc': (
                'union_list_dict',
                'list[str]',
            ),
            'msg': 'Input should be a valid list',
            'type': 'list_type',
        },
        {
            'input': 'hello=world',
            'loc': (
                'union_list_dict',
                'dict[str,any]',
            ),
            'msg': 'Input should be a valid dictionary',
            'type': 'dict_type',
        },
    ]

    args = ['--union_list_dict', '["hello=world"]']
    cfg = Cfg(_cli_parse_args=args)
    assert cfg.model_dump() == {'union_list_dict': ['hello=world']}


def test_cli_nested_dict_arg():
    class Cfg(BaseSettings):
        check_dict: Dict[str, Any]

    args = ['--check_dict', '{"k1":{"a": 1}},{"k2":{"b": 2}}']
    cfg = Cfg(_cli_parse_args=args)
    assert cfg.model_dump() == {'check_dict': {'k1': {'a': 1}, 'k2': {'b': 2}}}

    with pytest.raises(SettingsError) as exc_info:
        args = ['--check_dict', '{"k1":{"a": 1}},"k2":{"b": 2}}']
        cfg = Cfg(_cli_parse_args=args)
    assert (
        str(exc_info.value)
        == 'Parsing error encountered for check_dict: not enough values to unpack (expected 2, got 1)'
    )

    with pytest.raises(SettingsError) as exc_info:
        args = ['--check_dict', '{"k1":{"a": 1}},{"k2":{"b": 2}']
        cfg = Cfg(_cli_parse_args=args)
    assert str(exc_info.value) == 'Parsing error encountered for check_dict: Missing end delimiter "}"'


def test_cli_subcommand_with_positionals():
    class FooPlugin(BaseModel):
        my_feature: bool = False

    class BarPlugin(BaseModel):
        my_feature: bool = False

    class Plugins(BaseModel):
        foo: CliSubCommand[FooPlugin]
        bar: CliSubCommand[BarPlugin]

    class Clone(BaseModel):
        repository: CliPositionalArg[str]
        directory: CliPositionalArg[str]
        local: bool = False
        shared: bool = False

    class Init(BaseModel):
        directory: CliPositionalArg[str]
        quiet: bool = False
        bare: bool = False

    class Git(BaseSettings):
        clone: CliSubCommand[Clone]
        init: CliSubCommand[Init]
        plugins: CliSubCommand[Plugins]

    git = Git(_cli_parse_args=['init', '--quiet', 'true', 'dir/path'])
    assert git.model_dump() == {
        'clone': None,
        'init': {'directory': 'dir/path', 'quiet': True, 'bare': False},
        'plugins': None,
    }

    git = Git(_cli_parse_args=['clone', 'repo', '.', '--shared', 'true'])
    assert git.model_dump() == {
        'clone': {'repository': 'repo', 'directory': '.', 'local': False, 'shared': True},
        'init': None,
        'plugins': None,
    }

    git = Git(_cli_parse_args=['plugins', 'bar'])
    assert git.model_dump() == {
        'clone': None,
        'init': None,
        'plugins': {'foo': None, 'bar': {'my_feature': False}},
    }


def test_cli_union_similar_sub_models():
    class ChildA(BaseModel):
        name: str = 'child a'
        diff_a: str = 'child a difference'

    class ChildB(BaseModel):
        name: str = 'child b'
        diff_b: str = 'child b difference'

    class Cfg(BaseSettings):
        child: Union[ChildA, ChildB]

    cfg = Cfg(_cli_parse_args=['--child.name', 'new name a', '--child.diff_a', 'new diff a'])
    assert cfg.model_dump() == {'child': {'name': 'new name a', 'diff_a': 'new diff a'}}


def test_cli_enums():
    class Pet(IntEnum):
        dog = 0
        cat = 1
        bird = 2

    class Cfg(BaseSettings):
        pet: Pet

    cfg = Cfg(_cli_parse_args=['--pet', 'cat'])
    assert cfg.model_dump() == {'pet': Pet.cat}

    with pytest.raises(ValidationError) as exc_info:
        Cfg(_cli_parse_args=['--pet', 'rock'])
    assert exc_info.value.errors(include_url=False) == [
        {
            'type': 'enum',
            'loc': ('pet',),
            'msg': 'Input should be 0, 1 or 2',
            'input': 'rock',
            'ctx': {'expected': '0, 1 or 2'},
        }
    ]


def test_cli_literals():
    class Cfg(BaseSettings):
        pet: Literal['dog', 'cat', 'bird']

    cfg = Cfg(_cli_parse_args=['--pet', 'cat'])
    assert cfg.model_dump() == {'pet': 'cat'}

    with pytest.raises(ValidationError) as exc_info:
        Cfg(_cli_parse_args=['--pet', 'rock'])
    assert exc_info.value.errors(include_url=False) == [
        {
            'ctx': {'expected': "'dog', 'cat' or 'bird'"},
            'type': 'literal_error',
            'loc': ('pet',),
            'msg': "Input should be 'dog', 'cat' or 'bird'",
            'input': 'rock',
        }
    ]


def test_cli_annotation_exceptions(monkeypatch):
    class SubCmdAlt(BaseModel):
        pass

    class SubCmd(BaseModel):
        pass

    with monkeypatch.context() as m:
        m.setattr(sys, 'argv', ['example.py', '--help'])

        with pytest.raises(SettingsError) as exc_info:

            class SubCommandNotOutermost(BaseSettings, cli_parse_args=True):
                subcmd: Union[int, CliSubCommand[SubCmd]]

            SubCommandNotOutermost()
        assert str(exc_info.value) == 'CliSubCommand is not outermost annotation for SubCommandNotOutermost.subcmd'

        with pytest.raises(SettingsError) as exc_info:

            class SubCommandHasDefault(BaseSettings, cli_parse_args=True):
                subcmd: CliSubCommand[SubCmd] = SubCmd()

            SubCommandHasDefault()
        assert str(exc_info.value) == 'subcommand argument SubCommandHasDefault.subcmd has a default value'

        with pytest.raises(SettingsError) as exc_info:

            class SubCommandMultipleTypes(BaseSettings, cli_parse_args=True):
                subcmd: CliSubCommand[Union[SubCmd, SubCmdAlt]]

            SubCommandMultipleTypes()
        assert str(exc_info.value) == 'subcommand argument SubCommandMultipleTypes.subcmd has multiple types'

        with pytest.raises(SettingsError) as exc_info:

            class SubCommandNotModel(BaseSettings, cli_parse_args=True):
                subcmd: CliSubCommand[str]

            SubCommandNotModel()
        assert str(exc_info.value) == 'subcommand argument SubCommandNotModel.subcmd is not derived from BaseModel'

        with pytest.raises(SettingsError) as exc_info:

            class PositionalArgNotOutermost(BaseSettings, cli_parse_args=True):
                pos_arg: Union[int, CliPositionalArg[str]]

            PositionalArgNotOutermost()
        assert (
            str(exc_info.value) == 'CliPositionalArg is not outermost annotation for PositionalArgNotOutermost.pos_arg'
        )

        with pytest.raises(SettingsError) as exc_info:

            class PositionalArgHasDefault(BaseSettings, cli_parse_args=True):
                pos_arg: CliPositionalArg[str] = 'bad'

            PositionalArgHasDefault()
        assert str(exc_info.value) == 'positional argument PositionalArgHasDefault.pos_arg has a default value'

    with pytest.raises(SettingsError) as exc_info:

        class InvalidCliParseArgsType(BaseSettings, cli_parse_args='invalid type'):
            val: int

        InvalidCliParseArgsType()
    assert str(exc_info.value) == "cli_parse_args must be List[str] or Tuple[str, ...], recieved <class 'str'>"


def test_cli_avoid_json(capsys, monkeypatch):
    class SubModel(BaseModel):
        v1: int

    class Settings(BaseSettings):
        sub_model: SubModel

        model_config = SettingsConfigDict(cli_parse_args=True)

    argparse_options_text = 'options' if sys.version_info >= (3, 10) else 'optional arguments'

    with monkeypatch.context() as m:
        m.setattr(sys, 'argv', ['example.py', '--help'])

        with pytest.raises(SystemExit):
            Settings(_cli_avoid_json=False)

        assert (
            capsys.readouterr().out
            == f"""usage: example.py [-h] [--sub_model JSON] [--sub_model.v1 int]

{argparse_options_text}:
  -h, --help          show this help message and exit

sub_model options:
  --sub_model JSON    set sub_model from JSON string
  --sub_model.v1 int  (required)
"""
        )

        with pytest.raises(SystemExit):
            Settings(_cli_avoid_json=True)

        assert (
            capsys.readouterr().out
            == f"""usage: example.py [-h] [--sub_model.v1 int]

{argparse_options_text}:
  -h, --help          show this help message and exit

sub_model options:
  --sub_model.v1 int  (required)
"""
        )


def test_cli_remove_empty_groups(capsys, monkeypatch):
    class SubModel(BaseModel):
        pass

    class Settings(BaseSettings):
        sub_model: SubModel

        model_config = SettingsConfigDict(cli_parse_args=True)

    argparse_options_text = 'options' if sys.version_info >= (3, 10) else 'optional arguments'

    with monkeypatch.context() as m:
        m.setattr(sys, 'argv', ['example.py', '--help'])

        with pytest.raises(SystemExit):
            Settings(_cli_avoid_json=False)

        assert (
            capsys.readouterr().out
            == f"""usage: example.py [-h] [--sub_model JSON]

{argparse_options_text}:
  -h, --help        show this help message and exit

sub_model options:
  --sub_model JSON  set sub_model from JSON string
"""
        )

        with pytest.raises(SystemExit):
            Settings(_cli_avoid_json=True)

        assert (
            capsys.readouterr().out
            == f"""usage: example.py [-h]

{argparse_options_text}:
  -h, --help  show this help message and exit
"""
        )


def test_cli_hide_none_type(capsys, monkeypatch):
    class Settings(BaseSettings):
        v0: Optional[str]

        model_config = SettingsConfigDict(cli_parse_args=True)

    argparse_options_text = 'options' if sys.version_info >= (3, 10) else 'optional arguments'

    with monkeypatch.context() as m:
        m.setattr(sys, 'argv', ['example.py', '--help'])

        with pytest.raises(SystemExit):
            Settings(_cli_hide_none_type=False)

        assert (
            capsys.readouterr().out
            == f"""usage: example.py [-h] [--v0 {{str,null}}]

{argparse_options_text}:
  -h, --help       show this help message and exit
  --v0 {{str,null}}  (required)
"""
        )

        with pytest.raises(SystemExit):
            Settings(_cli_hide_none_type=True)

        assert (
            capsys.readouterr().out
            == f"""usage: example.py [-h] [--v0 str]

{argparse_options_text}:
  -h, --help  show this help message and exit
  --v0 str    (required)
"""
        )


def test_cli_use_class_docs_for_groups(capsys, monkeypatch):
    class SubModel(BaseModel):
        """The help text from the class docstring"""

        v1: int

    class Settings(BaseSettings):
        """My application help text."""

        sub_model: SubModel = Field(description='The help text from the field description')

        model_config = SettingsConfigDict(cli_parse_args=True)

    argparse_options_text = 'options' if sys.version_info >= (3, 10) else 'optional arguments'

    with monkeypatch.context() as m:
        m.setattr(sys, 'argv', ['example.py', '--help'])

        with pytest.raises(SystemExit):
            Settings(_cli_use_class_docs_for_groups=False)

        assert (
            capsys.readouterr().out
            == f"""usage: example.py [-h] [--sub_model JSON] [--sub_model.v1 int]

My application help text.

{argparse_options_text}:
  -h, --help          show this help message and exit

sub_model options:
  The help text from the field description

  --sub_model JSON    set sub_model from JSON string
  --sub_model.v1 int  (required)
"""
        )

        with pytest.raises(SystemExit):
            Settings(_cli_use_class_docs_for_groups=True)

        assert (
            capsys.readouterr().out
            == f"""usage: example.py [-h] [--sub_model JSON] [--sub_model.v1 int]

My application help text.

{argparse_options_text}:
  -h, --help          show this help message and exit

sub_model options:
  The help text from the class docstring

  --sub_model JSON    set sub_model from JSON string
  --sub_model.v1 int  (required)
"""
        )


def test_cli_enforce_required(env):
    class Settings(BaseSettings):
        my_required_field: str

    env.set('MY_REQUIRED_FIELD', 'hello from environment')

    assert Settings(_cli_parse_args=[], _cli_enforce_required=False).model_dump() == {
        'my_required_field': 'hello from environment'
    }

    with pytest.raises(SystemExit):
        Settings(_cli_parse_args=[], _cli_enforce_required=True).model_dump()


@pytest.mark.parametrize('parser_type', [pytest.Parser, argparse.ArgumentParser, CliDummyParser])
@pytest.mark.parametrize('prefix', ['', 'cfg'])
def test_cli_user_settings_source(parser_type, prefix):
    class Cfg(BaseSettings):
        pet: Literal['dog', 'cat', 'bird'] = 'bird'

    if parser_type is pytest.Parser:
        parser = pytest.Parser(_ispytest=True)
        parse_args = parser.parse
        add_arg = parser.addoption
        cli_cfg_settings = CliSettingsSource(
            Cfg,
            cli_prefix=prefix,
            root_parser=parser,
            parse_args_method=pytest.Parser.parse,
            add_argument_method=pytest.Parser.addoption,
            add_argument_group_method=pytest.Parser.getgroup,
            add_parser_method=None,
            add_subparsers_method=None,
            formatter_class=None,
        )
    elif parser_type is CliDummyParser:
        parser = CliDummyParser()
        parse_args = parser.parse_args
        add_arg = parser.add_argument
        cli_cfg_settings = CliSettingsSource(
            Cfg,
            cli_prefix=prefix,
            root_parser=parser,
            parse_args_method=CliDummyParser.parse_args,
            add_argument_method=CliDummyParser.add_argument,
            add_argument_group_method=CliDummyParser.add_argument_group,
            add_parser_method=CliDummySubParsers.add_parser,
            add_subparsers_method=CliDummyParser.add_subparsers,
        )
    else:
        parser = argparse.ArgumentParser()
        parse_args = parser.parse_args
        add_arg = parser.add_argument
        cli_cfg_settings = CliSettingsSource(Cfg, cli_prefix=prefix, root_parser=parser)

    add_arg('--fruit', choices=['pear', 'kiwi', 'lime'])

    args = ['--fruit', 'pear']
    parsed_args = parse_args(args)
    assert Cfg(_cli_settings_source=cli_cfg_settings(parsed_args=parsed_args)).model_dump() == {'pet': 'bird'}
    assert Cfg(_cli_settings_source=cli_cfg_settings(args=args)).model_dump() == {'pet': 'bird'}
    assert Cfg(_cli_settings_source=cli_cfg_settings(args=False)).model_dump() == {'pet': 'bird'}

    arg_prefix = f'{prefix}.' if prefix else ''
    args = ['--fruit', 'kiwi', f'--{arg_prefix}pet', 'dog']
    parsed_args = parse_args(args)
    assert Cfg(_cli_settings_source=cli_cfg_settings(parsed_args=parsed_args)).model_dump() == {'pet': 'dog'}
    assert Cfg(_cli_settings_source=cli_cfg_settings(args=args)).model_dump() == {'pet': 'dog'}
    assert Cfg(_cli_settings_source=cli_cfg_settings(args=False)).model_dump() == {'pet': 'bird'}

    parsed_args = parse_args(['--fruit', 'kiwi', f'--{arg_prefix}pet', 'cat'])
    assert Cfg(_cli_settings_source=cli_cfg_settings(parsed_args=vars(parsed_args))).model_dump() == {'pet': 'cat'}
    assert Cfg(_cli_settings_source=cli_cfg_settings(args=False)).model_dump() == {'pet': 'bird'}


@pytest.mark.parametrize('prefix', ['', 'cfg'])
def test_cli_dummy_user_settings_with_subcommand(prefix):
    class DogCommands(BaseModel):
        name: str = 'Bob'
        command: Literal['roll', 'bark', 'sit'] = 'sit'

    class Cfg(BaseSettings):
        pet: Literal['dog', 'cat', 'bird'] = 'bird'
        command: CliSubCommand[DogCommands]

    parser = CliDummyParser()
    cli_cfg_settings = CliSettingsSource(
        Cfg,
        root_parser=parser,
        cli_prefix=prefix,
        parse_args_method=CliDummyParser.parse_args,
        add_argument_method=CliDummyParser.add_argument,
        add_argument_group_method=CliDummyParser.add_argument_group,
        add_parser_method=CliDummySubParsers.add_parser,
        add_subparsers_method=CliDummyParser.add_subparsers,
    )

    parser.add_argument('--fruit', choices=['pear', 'kiwi', 'lime'])

    args = ['--fruit', 'pear']
    parsed_args = parser.parse_args(args)
    assert Cfg(_cli_settings_source=cli_cfg_settings(parsed_args=parsed_args)).model_dump() == {
        'pet': 'bird',
        'command': None,
    }
    assert Cfg(_cli_settings_source=cli_cfg_settings(args=args)).model_dump() == {
        'pet': 'bird',
        'command': None,
    }

    arg_prefix = f'{prefix}.' if prefix else ''
    args = ['--fruit', 'kiwi', f'--{arg_prefix}pet', 'dog']
    parsed_args = parser.parse_args(args)
    assert Cfg(_cli_settings_source=cli_cfg_settings(parsed_args=parsed_args)).model_dump() == {
        'pet': 'dog',
        'command': None,
    }
    assert Cfg(_cli_settings_source=cli_cfg_settings(args=args)).model_dump() == {
        'pet': 'dog',
        'command': None,
    }

    parsed_args = parser.parse_args(['--fruit', 'kiwi', f'--{arg_prefix}pet', 'cat'])
    assert Cfg(_cli_settings_source=cli_cfg_settings(parsed_args=vars(parsed_args))).model_dump() == {
        'pet': 'cat',
        'command': None,
    }

    args = ['--fruit', 'kiwi', f'--{arg_prefix}pet', 'dog', 'command', '--name', 'ralph', '--command', 'roll']
    parsed_args = parser.parse_args(args)
    assert Cfg(_cli_settings_source=cli_cfg_settings(parsed_args=vars(parsed_args))).model_dump() == {
        'pet': 'dog',
        'command': {'name': 'ralph', 'command': 'roll'},
    }
    assert Cfg(_cli_settings_source=cli_cfg_settings(args=args)).model_dump() == {
        'pet': 'dog',
        'command': {'name': 'ralph', 'command': 'roll'},
    }


def test_cli_user_settings_source_exceptions():
    class Cfg(BaseSettings):
        pet: Literal['dog', 'cat', 'bird'] = 'bird'

    with pytest.raises(SettingsError) as exc_info:
        args = ['--pet', 'dog']
        parsed_args = {'pet': 'dog'}
        cli_cfg_settings = CliSettingsSource(Cfg)
        Cfg(_cli_settings_source=cli_cfg_settings(args=args, parsed_args=parsed_args))
    assert str(exc_info.value) == '`args` and `parsed_args` are mutually exclusive'

    with pytest.raises(SettingsError) as exc_info:
        CliSettingsSource(Cfg, cli_prefix='.cfg')
    assert str(exc_info.value) == 'CLI settings source prefix is invalid: .cfg'

    with pytest.raises(SettingsError) as exc_info:
        CliSettingsSource(Cfg, cli_prefix='cfg.')
    assert str(exc_info.value) == 'CLI settings source prefix is invalid: cfg.'

    with pytest.raises(SettingsError) as exc_info:
        CliSettingsSource(Cfg, cli_prefix='123')
    assert str(exc_info.value) == 'CLI settings source prefix is invalid: 123'

    class Food(BaseModel):
        fruit: FruitsEnum = FruitsEnum.kiwi

    class CfgWithSubCommand(BaseSettings):
        pet: Literal['dog', 'cat', 'bird'] = 'bird'
        food: CliSubCommand[Food]

    with pytest.raises(SettingsError) as exc_info:
        CliSettingsSource(CfgWithSubCommand, add_subparsers_method=None)
    assert (
        str(exc_info.value)
        == 'cannot connect CLI settings source root parser: add_subparsers_method is set to `None` but is needed for connecting'
    )


@pytest.mark.parametrize(
    'value,expected',
    [
        (str, 'str'),
        ('foobar', 'str'),
        ('SomeForwardRefString', 'str'),  # included to document current behavior; could be changed
        (List['SomeForwardRef'], "List[ForwardRef('SomeForwardRef')]"),  # noqa: F821
        (Union[str, int], '{str,int}'),
        (list, 'list'),
        (List, 'List'),
        ([1, 2, 3], 'list'),
        (List[Dict[str, int]], 'List[Dict[str,int]]'),
        (Tuple[str, int, float], 'Tuple[str,int,float]'),
        (Tuple[str, ...], 'Tuple[str,...]'),
        (Union[int, List[str], Tuple[str, int]], '{int,List[str],Tuple[str,int]}'),
        (foobar, 'foobar'),
        (LoggedVar, 'LoggedVar'),
        (LoggedVar(), 'LoggedVar'),
        (Representation(), 'Representation()'),
        (typing.Literal[1, 2, 3], '{1,2,3}'),
        (typing_extensions.Literal[1, 2, 3], '{1,2,3}'),
        (typing.Literal['a', 'b', 'c'], '{a,b,c}'),
        (typing_extensions.Literal['a', 'b', 'c'], '{a,b,c}'),
        (SimpleSettings, 'JSON'),
        (Union[SimpleSettings, SettingWithIgnoreEmpty], 'JSON'),
        (Union[SimpleSettings, str, SettingWithIgnoreEmpty], '{JSON,str}'),
        (Union[str, SimpleSettings, SettingWithIgnoreEmpty], '{str,JSON}'),
        (Annotated[SimpleSettings, 'annotation'], 'JSON'),
        (DirectoryPath, 'Path'),
        (FruitsEnum, '{pear,kiwi,lime}'),
    ],
)
@pytest.mark.parametrize('hide_none_type', [True, False])
def test_cli_metavar_format(hide_none_type, value, expected):
    cli_settings = CliSettingsSource(SimpleSettings, cli_hide_none_type=hide_none_type)
    if hide_none_type:
        if value == [1, 2, 3] or isinstance(value, LoggedVar) or isinstance(value, Representation):
            pytest.skip()
        if value in ('foobar', 'SomeForwardRefString'):
            expected = f"ForwardRef('{value}')"  # forward ref implicit cast
        if typing_extensions.get_origin(value) is Union:
            args = typing_extensions.get_args(value)
            value = Union[args + (None,) if args else (value, None)]
        else:
            value = Union[(value, None)]
    assert cli_settings._metavar_format(value) == expected


@pytest.mark.skipif(sys.version_info < (3, 10), reason='requires python 3.10 or higher')
@pytest.mark.parametrize(
    'value_gen,expected',
    [
        (lambda: str | int, '{str,int}'),
        (lambda: list[int], 'list[int]'),
        (lambda: List[int], 'List[int]'),
        (lambda: list[dict[str, int]], 'list[dict[str,int]]'),
        (lambda: list[Union[str, int]], 'list[{str,int}]'),
        (lambda: list[str | int], 'list[{str,int}]'),
        (lambda: LoggedVar[int], 'LoggedVar[int]'),
        (lambda: LoggedVar[Dict[int, str]], 'LoggedVar[Dict[int,str]]'),
    ],
)
@pytest.mark.parametrize('hide_none_type', [True, False])
def test_cli_metavar_format_310(hide_none_type, value_gen, expected):
    value = value_gen()
    cli_settings = CliSettingsSource(SimpleSettings, cli_hide_none_type=hide_none_type)
    if hide_none_type:
        if typing_extensions.get_origin(value) is Union:
            args = typing_extensions.get_args(value)
            value = Union[args + (None,) if args else (value, None)]
        else:
            value = Union[(value, None)]
    assert cli_settings._metavar_format(value) == expected


@pytest.mark.skipif(sys.version_info < (3, 12), reason='requires python 3.12 or higher')
def test_cli_metavar_format_type_alias_312():
    exec(
        """
type TypeAliasInt = int
assert CliSettingsSource(SimpleSettings)._metavar_format(TypeAliasInt) == 'TypeAliasInt'
"""
    )


def test_json_file(tmp_path):
    p = tmp_path / '.env'
    p.write_text(
        """
    {"foobar": "Hello", "nested": {"nested_field": "world!"}, "null_field": null}
    """
    )

    class Nested(BaseModel):
        nested_field: str

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(json_file=p)
        foobar: str
        nested: Nested
        null_field: Union[str, None]

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (JsonConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.foobar == 'Hello'
    assert s.nested.nested_field == 'world!'


def test_json_no_file():
    class Settings(BaseSettings):
        model_config = SettingsConfigDict(json_file=None)

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (JsonConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {}


@pytest.mark.skipif(yaml is None, reason='pyYaml is not installed')
def test_yaml_file(tmp_path):
    p = tmp_path / '.env'
    p.write_text(
        """
    foobar: "Hello"
    null_field:
    nested:
        nested_field: "world!"
    """
    )

    class Nested(BaseModel):
        nested_field: str

    class Settings(BaseSettings):
        foobar: str
        nested: Nested
        null_field: Union[str, None]
        model_config = SettingsConfigDict(yaml_file=p)

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.foobar == 'Hello'
    assert s.nested.nested_field == 'world!'


@pytest.mark.skipif(yaml is None, reason='pyYaml is not installed')
def test_yaml_no_file():
    class Settings(BaseSettings):
        model_config = SettingsConfigDict(yaml_file=None)

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {}


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
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
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
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (TomlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {}


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_pyproject_toml_file(cd_tmp_path: Path):
    pyproject = cd_tmp_path / 'pyproject.toml'
    pyproject.write_text(
        """
    [tool.pydantic-settings]
    foobar = "Hello"

    [tool.pydantic-settings.nested]
    nested_field = "world!"
    """
    )

    class Nested(BaseModel):
        nested_field: str

    class Settings(BaseSettings):
        foobar: str
        nested: Nested
        model_config = SettingsConfigDict()

        @classmethod
        def settings_customise_sources(
            cls, settings_cls: Type[BaseSettings], **_kwargs: PydanticBaseSettingsSource
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (PyprojectTomlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.foobar == 'Hello'
    assert s.nested.nested_field == 'world!'


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_pyproject_toml_file_explicit(cd_tmp_path: Path):
    pyproject = cd_tmp_path / 'child' / 'grandchild' / 'pyproject.toml'
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text(
        """
    [tool.pydantic-settings]
    foobar = "Hello"

    [tool.pydantic-settings.nested]
    nested_field = "world!"
    """
    )
    (cd_tmp_path / 'pyproject.toml').write_text(
        """
    [tool.pydantic-settings]
    foobar = "fail"

    [tool.pydantic-settings.nested]
    nested_field = "fail"
    """
    )

    class Nested(BaseModel):
        nested_field: str

    class Settings(BaseSettings):
        foobar: str
        nested: Nested
        model_config = SettingsConfigDict()

        @classmethod
        def settings_customise_sources(
            cls, settings_cls: Type[BaseSettings], **_kwargs: PydanticBaseSettingsSource
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (PyprojectTomlConfigSettingsSource(settings_cls, pyproject),)

    s = Settings()
    assert s.foobar == 'Hello'
    assert s.nested.nested_field == 'world!'


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_pyproject_toml_file_parent(mocker: MockerFixture, tmp_path: Path):
    cwd = tmp_path / 'child' / 'grandchild' / 'cwd'
    cwd.mkdir(parents=True)
    mocker.patch('pydantic_settings.sources.Path.cwd', return_value=cwd)
    (cwd.parent.parent / 'pyproject.toml').write_text(
        """
    [tool.pydantic-settings]
    foobar = "Hello"

    [tool.pydantic-settings.nested]
    nested_field = "world!"
    """
    )
    (tmp_path / 'pyproject.toml').write_text(
        """
    [tool.pydantic-settings]
    foobar = "fail"

    [tool.pydantic-settings.nested]
    nested_field = "fail"
    """
    )

    class Nested(BaseModel):
        nested_field: str

    class Settings(BaseSettings):
        foobar: str
        nested: Nested
        model_config = SettingsConfigDict(pyproject_toml_depth=2)

        @classmethod
        def settings_customise_sources(
            cls, settings_cls: Type[BaseSettings], **_kwargs: PydanticBaseSettingsSource
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (PyprojectTomlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.foobar == 'Hello'
    assert s.nested.nested_field == 'world!'


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_pyproject_toml_file_header(cd_tmp_path: Path):
    pyproject = cd_tmp_path / 'subdir' / 'pyproject.toml'
    pyproject.parent.mkdir()
    pyproject.write_text(
        """
    [tool.pydantic-settings]
    foobar = "Hello"

    [tool.pydantic-settings.nested]
    nested_field = "world!"

    [tool."my.tool".foo]
    status = "success"
    """
    )

    class Settings(BaseSettings):
        status: str
        model_config = SettingsConfigDict(extra='forbid', pyproject_toml_table_header=('tool', 'my.tool', 'foo'))

        @classmethod
        def settings_customise_sources(
            cls, settings_cls: Type[BaseSettings], **_kwargs: PydanticBaseSettingsSource
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (PyprojectTomlConfigSettingsSource(settings_cls, pyproject),)

    s = Settings()
    assert s.status == 'success'


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
@pytest.mark.parametrize('depth', [0, 99])
def test_pyproject_toml_no_file(cd_tmp_path: Path, depth: int):
    class Settings(BaseSettings):
        model_config = SettingsConfigDict(pyproject_toml_depth=depth)

        @classmethod
        def settings_customise_sources(
            cls, settings_cls: Type[BaseSettings], **_kwargs: PydanticBaseSettingsSource
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (PyprojectTomlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {}


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
def test_pyproject_toml_no_file_explicit(tmp_path: Path):
    pyproject = tmp_path / 'child' / 'pyproject.toml'
    (tmp_path / 'pyproject.toml').write_text('[tool.pydantic-settings]\nfield = "fail"')

    class Settings(BaseSettings):
        model_config = SettingsConfigDict()

        field: Optional[str] = None

        @classmethod
        def settings_customise_sources(
            cls, settings_cls: Type[BaseSettings], **_kwargs: PydanticBaseSettingsSource
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (PyprojectTomlConfigSettingsSource(settings_cls, pyproject),)

    s = Settings()
    assert s.model_dump() == {'field': None}


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomli is None, reason='tomli/tomllib is not installed')
@pytest.mark.parametrize('depth', [0, 1, 2])
def test_pyproject_toml_no_file_too_shallow(depth: int, mocker: MockerFixture, tmp_path: Path):
    cwd = tmp_path / 'child' / 'grandchild' / 'cwd'
    cwd.mkdir(parents=True)
    mocker.patch('pydantic_settings.sources.Path.cwd', return_value=cwd)
    (tmp_path / 'pyproject.toml').write_text(
        """
    [tool.pydantic-settings]
    foobar = "fail"

    [tool.pydantic-settings.nested]
    nested_field = "fail"
    """
    )

    class Nested(BaseModel):
        nested_field: Optional[str] = None

    class Settings(BaseSettings):
        foobar: Optional[str] = None
        nested: Nested = Nested()
        model_config = SettingsConfigDict(pyproject_toml_depth=depth)

        @classmethod
        def settings_customise_sources(
            cls, settings_cls: Type[BaseSettings], **_kwargs: PydanticBaseSettingsSource
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (PyprojectTomlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert not s.foobar
    assert not s.nested.nested_field


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
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (TomlConfigSettingsSource(settings_cls, toml_file=[p1, p2]),)

    s = Settings()
    assert s.model_dump() == {'toml1': 1, 'toml2': 2}


@pytest.mark.skipif(yaml is None, reason='pyYAML is not installed')
def test_multiple_file_yaml(tmp_path):
    p3 = tmp_path / '.env.yaml3'
    p4 = tmp_path / '.env.yaml4'
    p3.write_text(
        """
    yaml3: 3
    """
    )
    p4.write_text(
        """
    yaml4: 4
    """
    )

    class Settings(BaseSettings):
        yaml3: int
        yaml4: int

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (YamlConfigSettingsSource(settings_cls, yaml_file=[p3, p4]),)

    s = Settings()
    assert s.model_dump() == {'yaml3': 3, 'yaml4': 4}


def test_multiple_file_json(tmp_path):
    p5 = tmp_path / '.env.json5'
    p6 = tmp_path / '.env.json6'

    with open(p5, 'w') as f5:
        json.dump({'json5': 5}, f5)
    with open(p6, 'w') as f6:
        json.dump({'json6': 6}, f6)

    class Settings(BaseSettings):
        json5: int
        json6: int

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: Type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> Tuple[PydanticBaseSettingsSource, ...]:
            return (JsonConfigSettingsSource(settings_cls, json_file=[p5, p6]),)

    s = Settings()
    assert s.model_dump() == {'json5': 5, 'json6': 6}


def test_dotenv_with_alias_and_env_prefix(tmp_path):
    p = tmp_path / '.env'
    p.write_text('xxx__foo=1\nxxx__bar=2')

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_file=p, env_prefix='xxx__')

        foo: str = ''
        bar_alias: str = Field('', validation_alias='xxx__bar')

    s = Settings()
    assert s.model_dump() == {'foo': '1', 'bar_alias': '2'}

    class Settings1(BaseSettings):
        model_config = SettingsConfigDict(env_file=p, env_prefix='xxx__')

        foo: str = ''
        bar_alias: str = Field('', alias='bar')

    with pytest.raises(ValidationError) as exc_info:
        Settings1()
    assert exc_info.value.errors(include_url=False) == [
        {'type': 'extra_forbidden', 'loc': ('xxx__bar',), 'msg': 'Extra inputs are not permitted', 'input': '2'}
    ]


def test_dotenv_with_alias_and_env_prefix_nested(tmp_path):
    p = tmp_path / '.env'
    p.write_text('xxx__bar=0\nxxx__nested__a=1\nxxx__nested__b=2')

    class NestedSettings(BaseModel):
        a: str = 'a'
        b: str = 'b'

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='xxx__', env_nested_delimiter='__', env_file=p)

        foo: str = ''
        bar_alias: str = Field('', alias='xxx__bar')
        nested_alias: NestedSettings = Field(default_factory=NestedSettings, alias='xxx__nested')

    s = Settings()
    assert s.model_dump() == {'foo': '', 'bar_alias': '0', 'nested_alias': {'a': '1', 'b': '2'}}


def test_dotenv_with_extra_and_env_prefix(tmp_path):
    p = tmp_path / '.env'
    p.write_text('xxx__foo=1\nxxx__extra_var=extra_value')

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(extra='allow', env_file=p, env_prefix='xxx__')

        foo: str = ''

    s = Settings()
    assert s.model_dump() == {'foo': '1', 'extra_var': 'extra_value'}


def test_nested_field_with_alias_init_source():
    class NestedSettings(BaseModel):
        foo: str = Field(alias='fooAlias')

    class Settings(BaseSettings):
        nested_foo: NestedSettings

    s = Settings(nested_foo=NestedSettings(fooAlias='EXAMPLE'))
    assert s.model_dump() == {'nested_foo': {'foo': 'EXAMPLE'}}


def test_nested_models_as_dict_value(env):
    class NestedSettings(BaseModel):
        foo: Dict[str, int]

    class Settings(BaseSettings):
        nested: NestedSettings
        sub_dict: Dict[str, NestedSettings]

        model_config = SettingsConfigDict(env_nested_delimiter='__')

    env.set('nested__foo', '{"a": 1}')
    env.set('sub_dict__bar__foo', '{"b": 2}')
    s = Settings()
    assert s.model_dump() == {'nested': {'foo': {'a': 1}}, 'sub_dict': {'bar': {'foo': {'b': 2}}}}


def test_env_nested_dict_value(env):
    class Settings(BaseSettings):
        nested: Dict[str, Dict[str, Dict[str, str]]]

        model_config = SettingsConfigDict(env_nested_delimiter='__')

    env.set('nested__foo__a__b', 'bar')
    s = Settings()
    assert s.model_dump() == {'nested': {'foo': {'a': {'b': 'bar'}}}}


def test_nested_models_leaf_vs_deeper_env_dict_assumed(env):
    class NestedSettings(BaseModel):
        foo: str

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_nested_delimiter='__')

        nested: NestedSettings

    env.set('nested__foo', 'string')
    env.set(
        'nested__foo__bar',
        'this should not be evaluated, since foo is a string by annotation and not a dict',
    )
    env.set(
        'nested__foo__bar__baz',
        'one more',
    )
    s = Settings()
    assert s.model_dump() == {'nested': {'foo': 'string'}}


def test_case_insensitive_nested_optional(env):
    class NestedSettings(BaseModel):
        FOO: str
        BaR: int

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_nested_delimiter='__', case_sensitive=False)

        nested: Optional[NestedSettings]

    env.set('nested__FoO', 'string')
    env.set('nested__bar', '123')
    s = Settings()
    assert s.model_dump() == {'nested': {'BaR': 123, 'FOO': 'string'}}


def test_case_insensitive_nested_list(env):
    class NestedSettings(BaseModel):
        FOO: List[str]

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_nested_delimiter='__', case_sensitive=False)

        nested: Optional[NestedSettings]

    env.set('nested__FOO', '["string1", "string2"]')
    s = Settings()
    assert s.model_dump() == {'nested': {'FOO': ['string1', 'string2']}}
