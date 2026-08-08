from __future__ import annotations as _annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, AliasGenerator, AnyHttpUrl, BaseModel, Field
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


def test_nested_model_alias_merged_env_and_dotenv(tmp_path: Path, env):
    """Regression for https://github.com/pydantic/pydantic-settings/issues/923

    A nested model field aliased by a plain string must also be reachable by its real
    field name, so that a lower-priority source (e.g. ``.env``) using the field name
    prefix can populate -- and be merged with -- the nested model populated from the
    alias prefix in env.
    """
    env_file = tmp_path / '.env'
    env_file.write_text('SUBMODEL_VAR1="var1 from dotenv"\nSUBMODEL_VAR2="var2 from dotenv"\n')

    class SubModel(BaseModel):
        var1: str | None = None
        var2: str | None = None

    class Settings(BaseSettings):
        submodel: SubModel | None = Field(alias='SUB', default=None)
        model_config = SettingsConfigDict(env_file=env_file, env_nested_delimiter='_')

    env.set('SUB_VAR1', 'var1 from env')
    s = Settings()
    assert s.submodel is not None
    assert s.submodel.var1 == 'var1 from env'
    assert s.submodel.var2 == 'var2 from dotenv'


def test_nested_model_alias_field_name_dotenv_only(tmp_path: Path):
    """Field-name prefix should populate an aliased nested model from dotenv alone."""
    env_file = tmp_path / '.env'
    env_file.write_text('SUBMODEL_VAR1="var1 from dotenv"\n')

    class SubModel(BaseModel):
        var1: str

    class Settings(BaseSettings):
        submodel: SubModel = Field(alias='SUB')
        model_config = SettingsConfigDict(env_file=env_file, env_nested_delimiter='_')

    s = Settings()
    assert s.submodel.var1 == 'var1 from dotenv'


def test_nested_model_alias_choices_field_name_env(env):
    """AliasChoices listing both the alias and field name still resolve from env."""

    class SubModel(BaseModel):
        var1: str

    class Settings(BaseSettings):
        submodel: SubModel = Field(validation_alias=AliasChoices('SUB', 'SUBMODEL'))
        model_config = SettingsConfigDict(env_nested_delimiter='_')

    env.set('SUBMODEL_VAR1', 'from env')
    s = Settings()
    assert s.submodel.var1 == 'from env'


def test_scalar_alias_field_name_does_not_claim_nested_prefix(tmp_path: Path):
    """A scalar field's alias must not be broadened to its field name (see #923 scoping)."""
    env_file = tmp_path / '.env'
    env_file.write_text('SUBMODEL_VAR1="x"\n')

    class Settings(BaseSettings):
        sub: str = Field(alias='SUB', default='d')
        model_config = SettingsConfigDict(env_file=env_file, env_nested_delimiter='_', extra='allow')

    s = Settings()
    assert s.sub == 'd'
    assert s.model_extra == {'submodel_var1': 'x'}


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
