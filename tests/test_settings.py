import dataclasses
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Generic, List, Optional, Set, Tuple, Type, TypeVar, Union

import pytest
from annotated_types import MinLen
from pydantic import (
    AliasChoices,
    AliasPath,
    BaseModel,
    Field,
    HttpUrl,
    Json,
    RootModel,
    SecretStr,
    ValidationError,
)
from pydantic import (
    dataclasses as pydantic_dataclasses,
)
from pydantic.fields import FieldInfo
from typing_extensions import Annotated

from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    InitSettingsSource,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SecretsSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
    YamlConfigSettingsSource,
)
from pydantic_settings.sources import SettingsError, read_env_file

try:
    import dotenv
except ImportError:
    dotenv = None
try:
    import yaml
except ImportError:
    yaml = None
try:
    import tomlkit
except ImportError:
    tomlkit = None


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
    class SubModel(BaseSettings):
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


def test_env_deep_override(env):
    class DeepSubModel(BaseModel):
        v4: str

    class SubModel(BaseModel):
        v1: str
        v2: bytes
        v3: int
        deep: DeepSubModel

    class Settings(BaseSettings, env_nested_delimiter='__'):
        v0: str
        sub_model: SubModel

        @classmethod
        def settings_customise_sources(
            cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
        ):
            return env_settings, dotenv_settings, init_settings, file_secret_settings

    env.set('SUB_MODEL__DEEP__V4', 'override-v4')

    s_final = {'v0': '0', 'sub_model': {'v1': 'init-v1', 'v2': b'init-v2', 'v3': 3, 'deep': {'v4': 'override-v4'}}}

    s = Settings(v0='0', sub_model={'v1': 'init-v1', 'v2': b'init-v2', 'v3': 3, 'deep': {'v4': 'init-v4'}})
    assert s.model_dump() == s_final

    s = Settings(v0='0', sub_model=SubModel(v1='init-v1', v2=b'init-v2', v3=3, deep=DeepSubModel(v4='init-v4')))
    assert s.model_dump() == s_final

    s = Settings(v0='0', sub_model=SubModel(v1='init-v1', v2=b'init-v2', v3=3, deep={'v4': 'init-v4'}))
    assert s.model_dump() == s_final

    s = Settings(v0='0', sub_model={'v1': 'init-v1', 'v2': b'init-v2', 'v3': 3, 'deep': DeepSubModel(v4='init-v4')})
    assert s.model_dump() == s_final


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


@pytest.mark.skipif(sys.version_info >= (3, 11) or tomlkit, reason='tomlkit/tomllib is installed')
def test_toml_not_installed(tmp_path):
    p = tmp_path / '.env'
    p.write_text(
        """
    foobar = "Hello"
    """
    )

    class Settings(BaseSettings):
        foobar: str
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

    with pytest.raises(ImportError, match=r'^tomlkit is not installed, run `pip install pydantic-settings\[toml\]`$'):
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


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomlkit is None, reason='tomlkit/tomllib is not installed')
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


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomlkit is None, reason='tomlkit/tomllib is not installed')
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


@pytest.mark.skipif(sys.version_info <= (3, 11) and tomlkit is None, reason='tomlkit/tomllib is not installed')
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
