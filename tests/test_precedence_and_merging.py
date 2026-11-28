from __future__ import annotations as _annotations

from pathlib import Path
from typing import Literal

import pytest
from pydantic import AliasChoices, AliasGenerator, AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


def test_init_kwargs_override_env_for_alias_with_populate_by_name(env):
    class Settings(BaseSettings):
        abc: AnyHttpUrl = Field(validation_alias='my_abc')
        model_config = SettingsConfigDict(populate_by_name=True, extra='allow')

    env.set('MY_ABC', 'http://localhost.com')
    # Passing by field name should be accepted (populate_by_name=True) and should
    # override env-derived value. Also ensures init > env precedence with validation_alias.
    assert str(Settings(abc='http://prod.localhost.com/').abc) == 'http://prod.localhost.com/'


def test_precedence_init_over_env(tmp_path: Path, env):
    class Settings(BaseSettings):
        foo: str

    env.set('FOO', 'from-env')
    s = Settings(foo='from-init')
    assert s.foo == 'from-init'


def test_precedence_env_over_dotenv(tmp_path: Path, env):
    env_file = tmp_path / '.env'
    env_file.write_text('FOO=from-dotenv\n')

    class Settings(BaseSettings):
        foo: str

        model_config = SettingsConfigDict(env_file=env_file)

    env.set('FOO', 'from-env')
    s = Settings()
    assert s.foo == 'from-env'


def test_precedence_dotenv_over_secrets(tmp_path: Path):
    # create dotenv
    env_file = tmp_path / '.env'
    env_file.write_text('FOO=from-dotenv\n')

    # create secrets directory with same key
    secrets_dir = tmp_path / 'secrets'
    secrets_dir.mkdir()
    (secrets_dir / 'FOO').write_text('from-secrets\n')

    class Settings(BaseSettings):
        foo: str

        model_config = SettingsConfigDict(env_file=env_file, secrets_dir=secrets_dir)

    # No env set, dotenv should override secrets
    s = Settings()
    assert s.foo == 'from-dotenv'


def test_precedence_secrets_over_defaults(tmp_path: Path):
    secrets_dir = tmp_path / 'secrets'
    secrets_dir.mkdir()
    (secrets_dir / 'FOO').write_text('from-secrets\n')

    class Settings(BaseSettings):
        foo: str = 'from-default'

        model_config = SettingsConfigDict(secrets_dir=secrets_dir)

    s = Settings()
    assert s.foo == 'from-secrets'


def test_merging_preserves_earlier_values(tmp_path: Path, env):
    # Prove that merging preserves earlier source values: init -> env -> dotenv -> secrets -> defaults
    # We'll populate nested from dotenv and env parts, then set a default for a, and init for b
    env_file = tmp_path / '.env'
    env_file.write_text('NESTED={"x":1}\n')

    secrets_dir = tmp_path / 'secrets'
    secrets_dir.mkdir()
    (secrets_dir / 'NESTED').write_text('{"y": 2}')

    class Settings(BaseSettings):
        a: int = 10
        b: int = 0
        nested: dict

        model_config = SettingsConfigDict(env_file=env_file, secrets_dir=secrets_dir, env_nested_delimiter='__')

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ):
            # normal order; we want to assert deep merging
            return init_settings, env_settings, dotenv_settings, file_secret_settings

    # env contributes nested.y and overrides dotenv nested.x=1 if set; we'll set only y to prove merge
    env.set('NESTED__y', '3')
    # init contributes b, defaults contribute a
    s = Settings(b=20)
    assert s.a == 10  # defaults preserved
    assert s.b == 20  # init wins
    # nested: dotenv provides x=1; env provides y=3; deep merged => {x:1, y:3}
    assert s.nested == {'x': 1, 'y': 3}


def test_env_overrides_init_with_alias_choices_and_custom_source_order(env):
    """Regression test for https://github.com/pydantic/pydantic-settings/issues/812

    When using AliasChoices with an AliasGenerator and custom source ordering
    (env > init), env variables should take precedence over init kwargs even when
    different alias choices match in each source.
    """
    to_snake_or_camel = AliasGenerator(
        validation_alias=lambda field_name: AliasChoices(f'PREF_{field_name}', to_camel(field_name), field_name)
    )

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(alias_generator=to_snake_or_camel, extra='ignore')

        interval: int = Field(60, ge=60)
        data_store_path: str = '/data'

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return env_settings, init_settings, dotenv_settings, file_secret_settings

    # Env var using the PREF_ prefix (first alias choice) should override init
    env.set('PREF_INTERVAL', '120')
    s = Settings(interval=73)
    assert s.interval == 120

    # Env var using camelCase (second alias choice) should override init
    env.set('dataStorePath', '/env-data')
    s = Settings(data_store_path='/init-data')
    assert s.data_store_path == '/env-data'

    # Env var using field name (third alias choice) should override init
    env.pop('dataStorePath')
    env.set('data_store_path', '/env-data-2')
    s = Settings(data_store_path='/init-data')
    assert s.data_store_path == '/env-data-2'


def test_init_kwargs_override_env_with_alias_and_extra_forbid(env):
    # Reproduction for https://github.com/pydantic/pydantic-settings/issues/744
    class Settings(BaseSettings):
        env_kind: Literal['dev', 'hosted'] = Field(default='dev', alias='ENV_KIND2')
        model_config = SettingsConfigDict(populate_by_name=True, extra='forbid')

    env.set('ENV_KIND', 'dev')

    # This should work: init kwargs should override env vars
    # We saw intermittent failures due to non-deterministic set.pop(), it failed with:
    # pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
    # env_kind
    #   Extra inputs are not permitted [type=extra_forbidden, input_value='dev', input_type=str]
    s = Settings(env_kind='hosted')
    assert s.env_kind == 'hosted'


def test_nested_model_merging_alias_and_field_name(tmp_path: Path):
    """Test #923: Nested models are merged when one source uses field name and another uses alias."""
    env_file = tmp_path / '.env'
    env_file.write_text('SUBMODEL={"a": 1}\n')

    class SubModel(BaseModel):
        a: int
        b: int

    class Settings(BaseSettings):
        sub: SubModel = Field(validation_alias='SUBMODEL')
        model_config = SettingsConfigDict(
            env_file=env_file,
            populate_by_name=True,
            extra='forbid',
        )

    # Init passes 'sub' by field name; env_file provides 'SUBMODEL' by alias
    s = Settings(sub={'b': 2})
    assert s.sub.a == 1
    assert s.sub.b == 2


def test_nested_model_merging_alias_choices_across_sources(tmp_path: Path, env):
    """Test #923: Nested models merge when different sources use different AliasChoices."""
    env_file = tmp_path / '.env'
    env_file.write_text('SUB={"a": 10}\n')

    class SubModel(BaseModel):
        a: int
        b: int

    class Settings(BaseSettings):
        sub: SubModel = Field(validation_alias=AliasChoices('SUBMODEL', 'SUB'))
        model_config = SettingsConfigDict(
            env_file=env_file,
            env_nested_delimiter='__',
            extra='forbid',
        )

    # Env provides SUBMODEL__b=20; env_file provides SUB={"a": 10}
    env.set('SUBMODEL__b', '20')
    s = Settings()
    assert s.sub.a == 10
    assert s.sub.b == 20


def test_nested_submodel_field_alias_merging(tmp_path: Path):
    """Test #923: Nested submodel fields with aliases merge across sources."""
    env_file = tmp_path / '.env'
    env_file.write_text('SUB={"fa": 100}\n')

    class SubModel(BaseModel):
        field_a: int = Field(validation_alias=AliasChoices('fa', 'field_a'))
        field_b: int = Field(validation_alias='fb')
        model_config = ConfigDict(populate_by_name=True)

    class Settings(BaseSettings):
        sub: SubModel = Field(validation_alias='SUB')
        model_config = SettingsConfigDict(
            env_file=env_file,
            extra='forbid',
        )

    # Init provides field_b by field name; env_file provides fa by alias
    s = Settings(sub={'field_b': 200})
    assert s.sub.field_a == 100
    assert s.sub.field_b == 200


def test_nested_model_no_merge_when_populate_by_name_false(tmp_path: Path):
    """Test #923: When populate_by_name=False, field name in source is not matched to alias."""

    class SubModel(BaseModel):
        a: int = 1

    class Settings(BaseSettings):
        sub: SubModel = Field(validation_alias='SUBMODEL')
        model_config = SettingsConfigDict(
            populate_by_name=False,
            extra='forbid',
        )

    # Passing by field name should raise ValidationError because populate_by_name is False
    with pytest.raises(ValidationError):
        Settings(sub={'a': 2})


def test_nested_model_merging_case_sensitive(tmp_path: Path):
    """Test #923: Case sensitivity is respected when normalizing nested keys."""
    env_file = tmp_path / '.env'
    env_file.write_text('SUB={"a": 1}\n')

    class SubModel(BaseModel):
        a: int
        b: int

    class Settings(BaseSettings):
        sub: SubModel = Field(validation_alias='sub')
        model_config = SettingsConfigDict(
            env_file=env_file,
            case_sensitive=True,
            extra='forbid',
        )

    # With case_sensitive=True, 'SUB' in env_file does NOT match 'sub'
    with pytest.raises(ValidationError):
        Settings(sub={'b': 2})
