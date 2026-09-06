import json
from typing import Annotated

import pytest
from pydantic import AliasChoices, AliasPath, BaseModel, Field, ValidationError

from pydantic_settings import (
    BaseSettings,
    CliApp,
    CliSettingsSource,
    JsonConfigSettingsSource,
    NoExternalSources,
    SettingsConfigDict,
    SettingsError,
)


def test_environment_and_model_contract(env):
    class Settings(BaseSettings):
        fixed: Annotated[list[int], NoExternalSources] = [1]
        ordinary: int = 0

    env.set('FIXED', 'not JSON')
    env.set('ORDINARY', '2')
    assert Settings().model_dump() == {'fixed': [1], 'ordinary': 2}
    assert Settings(fixed=[3]).fixed == [3]
    assert 'fixed' in Settings.model_fields
    assert Settings.model_json_schema()['properties']['fixed']['type'] == 'array'
    assert Settings().model_fields_set == {'ordinary'}
    with pytest.raises(ValidationError):
        Settings(fixed=['invalid'])


@pytest.mark.parametrize('filtering', [None, 'match_prefix', 'only_existing'])
def test_dotenv_extras(tmp_path, filtering):
    path = tmp_path / '.env'
    path.write_text('APP_FIXED=not-json\nAPP_FIXED__value=not-json\nAPP_ORDINARY=2\n')

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_prefix='APP_', env_nested_delimiter='__')
        fixed: Annotated[dict[str, int], NoExternalSources] = {'value': 1}
        ordinary: int = 0

    Settings.model_config['dotenv_filtering'] = filtering
    assert Settings(_env_file=path).model_dump() == {'fixed': {'value': 1}, 'ordinary': 2}


def test_secret_source(tmp_path):
    (tmp_path / 'fixed').write_text('invalid')

    class Settings(BaseSettings):
        fixed: Annotated[int, NoExternalSources] = 1

    assert Settings(_secrets_dir=tmp_path).fixed == 1


@pytest.mark.parametrize('source_kind', ['json', 'custom'])
@pytest.mark.parametrize('alias', [None, 'OTHER', AliasChoices('OTHER', 'FALLBACK')])
def test_file_and_custom_sources(tmp_path, source_kind, alias):
    data = {'fixed': 'invalid', 'OTHER': 'invalid', 'FALLBACK': 'invalid', 'ordinary': 2}
    if alias is None:
        data = {'fixed': 'invalid', 'ordinary': 2}
    elif isinstance(alias, str):
        data.pop('FALLBACK')
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps(data))

    class Settings(BaseSettings):
        fixed: Annotated[int, NoExternalSources] = Field(1, validation_alias=alias)
        ordinary: int = 0

        @classmethod
        def settings_customise_sources(cls, settings_cls, init_settings, **kwargs):
            source = JsonConfigSettingsSource(settings_cls, path) if source_kind == 'json' else lambda: data
            return source, init_settings

    assert Settings().model_dump() == {'fixed': 1, 'ordinary': 2}
    assert Settings(**{alias if isinstance(alias, str) else 'OTHER' if alias else 'fixed': 3}).fixed == 3
    assert data['ordinary'] == 2
    assert 'fixed' in data


def test_shared_alias_path():
    data = {'group': {'fixed': 'invalid', 'ordinary': 2}}

    class Settings(BaseSettings):
        fixed: Annotated[int, NoExternalSources] = Field(1, validation_alias=AliasPath('group', 'fixed'))
        ordinary: int = Field(validation_alias=AliasPath('group', 'ordinary'))

        @classmethod
        def settings_customise_sources(cls, settings_cls, **kwargs):
            return (lambda: data,)

    assert Settings().model_dump() == {'fixed': 1, 'ordinary': 2}
    assert data['group']['fixed'] == 'invalid'


def test_alias_path_root_matches_excluded_field_name():
    data = {'group': {'fixed': 'invalid', 'ordinary': 2}}

    class Settings(BaseSettings):
        group: Annotated[int, NoExternalSources] = Field(1, validation_alias=AliasPath('group', 'fixed'))
        ordinary: int = Field(validation_alias=AliasPath('group', 'ordinary'))

        @classmethod
        def settings_customise_sources(cls, settings_cls, **kwargs):
            return (lambda: data,)

    assert Settings().model_dump() == {'group': 1, 'ordinary': 2}
    assert data == {'group': {'fixed': 'invalid', 'ordinary': 2}}


@pytest.mark.parametrize(
    'excluded_alias,ordinary_alias',
    [
        ('VALUE', 'VALUE'),
        ('VALUE', 'value'),
        (AliasChoices('FIRST', 'VALUE'), 'VALUE'),
        (AliasPath('group', 'value'), AliasPath('group', 'value')),
        ('group', AliasPath('group', 'value')),
        (AliasPath('group', 'value'), 'group'),
    ],
)
def test_reject_overlapping_external_field_paths(excluded_alias, ordinary_alias):
    class Settings(BaseSettings):
        secret: Annotated[str, NoExternalSources] = Field('default', validation_alias=excluded_alias)
        endpoint: str = Field('endpoint', validation_alias=ordinary_alias)

    with pytest.raises(SettingsError, match=r"NoExternalSources.*'secret'.*'endpoint'.*overlap"):
        Settings()


def test_case_sensitive_distinct_aliases():
    class Settings(BaseSettings):
        model_config = SettingsConfigDict(case_sensitive=True)
        secret: Annotated[str, NoExternalSources] = Field('default', validation_alias='VALUE')
        endpoint: str = Field(validation_alias='value')

        @classmethod
        def settings_customise_sources(cls, settings_cls, **kwargs):
            return (lambda: {'VALUE': 'ignored', 'value': 'kept'},)

    assert Settings().model_dump() == {'secret': 'default', 'endpoint': 'kept'}


def test_populate_by_name_overlapping_alias():
    class Settings(BaseSettings):
        model_config = SettingsConfigDict(populate_by_name=True)
        secret: Annotated[str, NoExternalSources] = Field('default', validation_alias='SECRET')
        endpoint: str = Field('endpoint', validation_alias='secret')

    with pytest.raises(SettingsError, match='overlap'):
        Settings()


def test_non_input_field_name_does_not_hide_another_fields_alias():
    class Settings(BaseSettings):
        secret: Annotated[str, NoExternalSources] = Field('default', validation_alias='PRIVATE')
        endpoint: str = Field(validation_alias='secret')

        @classmethod
        def settings_customise_sources(cls, settings_cls, **kwargs):
            return (lambda: {'PRIVATE': 'ignored', 'secret': 'kept'},)

    assert Settings().model_dump() == {'secret': 'default', 'endpoint': 'kept'}


def test_negative_alias_path_index_overlap():
    class Settings(BaseSettings):
        secret: Annotated[str, NoExternalSources] = Field('default', validation_alias=AliasPath('group', -1))
        endpoint: str = Field(validation_alias=AliasPath('group', 0))

        @classmethod
        def settings_customise_sources(cls, settings_cls, **kwargs):
            return (lambda: {'group': ['shared']},)

    with pytest.raises(SettingsError, match='overlap'):
        Settings()


def test_unmarked_shared_aliases_are_unchanged():
    class Settings(BaseSettings):
        first: str = Field(validation_alias='VALUE')
        second: str = Field(validation_alias='VALUE')

    assert Settings(VALUE='shared').model_dump() == {'first': 'shared', 'second': 'shared'}


def test_two_excluded_fields_can_share_an_alias():
    class Settings(BaseSettings):
        first: Annotated[str, NoExternalSources] = Field('first', validation_alias='VALUE')
        second: Annotated[str, NoExternalSources] = Field('second', validation_alias='VALUE')

        @classmethod
        def settings_customise_sources(cls, settings_cls, init_settings, **kwargs):
            return init_settings, lambda: {'VALUE': 'ignored'}

    assert Settings().model_dump() == {'first': 'first', 'second': 'second'}
    assert Settings(VALUE='explicit').model_dump() == {'first': 'explicit', 'second': 'explicit'}


@pytest.mark.parametrize('target', ['variable', 'alias', 'all'])
def test_cli_exclusion_uses_parser_destination(target, monkeypatch):
    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_prefix_target=target)
        fixed: Annotated[str, NoExternalSources] = Field('default', validation_alias='FIXED')

    source = CliSettingsSource(Settings, cli_prefix='app')
    resolve = source._resolve_parsed_args

    def check_args(parsed_args):
        assert 'FIXED' not in parsed_args
        return resolve(parsed_args)

    monkeypatch.setattr(source, '_resolve_parsed_args', check_args)
    assert CliApp.run(Settings, cli_args={'FIXED': 'external'}, cli_settings_source=source).fixed == 'default'


def test_cli_exclusion_preserves_shared_alias_path():
    class Settings(BaseSettings):
        fixed: Annotated[int, NoExternalSources] = Field(1, validation_alias=AliasPath('group', 'fixed'))
        ordinary: int = Field(validation_alias=AliasPath('group', 'ordinary'))

    source = CliSettingsSource(Settings)
    settings = CliApp.run(
        Settings, cli_args={'group': '{"fixed": "invalid", "ordinary": 2}'}, cli_settings_source=source
    )
    assert settings.model_dump() == {'fixed': 1, 'ordinary': 2}


def test_cli():
    class Settings(BaseSettings):
        fixed: Annotated[int, NoExternalSources] = 1
        ordinary: int = 0

    source = CliSettingsSource(Settings)
    assert '--fixed' not in source.root_parser.format_help()
    assert CliApp.run(Settings, cli_args=['--ordinary', '2']).model_dump() == {'fixed': 1, 'ordinary': 2}
    assert CliApp.serialize(Settings(fixed=3, ordinary=2)) == ['--ordinary', '2']
    assert CliApp.run(Settings, cli_args={'fixed': 'invalid', 'ordinary': 2}, cli_settings_source=source).fixed == 1


def test_whole_nested_field(env):
    class Nested(BaseModel):
        value: int = 1

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_nested_delimiter='__', nested_model_default_partial_update=True)
        fixed: Annotated[Nested, NoExternalSources] = Nested()

    env.set('FIXED__VALUE', 'invalid')
    assert Settings().fixed.value == 1
    assert Settings(fixed={'value': 3}).fixed.value == 3


def test_required_and_default_factory(env):
    calls = []

    def factory():
        calls.append(True)
        return [1]

    class Settings(BaseSettings):
        fixed: Annotated[int, NoExternalSources]
        generated: Annotated[list[int], NoExternalSources] = Field(default_factory=factory)

    env.set('FIXED', '2')
    env.set('GENERATED', 'invalid')
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert exc_info.value.errors()[0]['type'] == 'missing'
    calls.clear()
    settings = Settings(fixed=3)
    assert settings.model_dump() == {'fixed': 3, 'generated': [1]}
    assert calls == [True]
    assert Settings(fixed=3, generated=[4]).generated == [4]
    assert calls == [True]


@pytest.mark.parametrize('source_kind', ['json', 'custom'])
@pytest.mark.parametrize('index', [0, -2])
def test_shared_list_alias_path(tmp_path, source_kind, index):
    data = {'group': ['invalid', 2]}
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps(data))

    class Settings(BaseSettings):
        fixed: Annotated[int, NoExternalSources] = Field(
            1, validation_alias=AliasChoices(AliasPath('group', index), 'FALLBACK')
        )
        ordinary: int = Field(validation_alias=AliasPath('group', 1))

        @classmethod
        def settings_customise_sources(cls, settings_cls, **kwargs):
            return (JsonConfigSettingsSource(settings_cls, path) if source_kind == 'json' else lambda: data,)

    assert Settings().model_dump() == {'fixed': 1, 'ordinary': 2}
    assert data['group'] == ['invalid', 2]


@pytest.mark.parametrize('prefix', ['', 'app'])
def test_preparsed_cli_list(prefix):
    class Settings(BaseSettings):
        fixed: Annotated[list[int], NoExternalSources] = [1]

    source = CliSettingsSource(Settings, cli_prefix=prefix)
    key = f'{prefix}.fixed' if prefix else 'fixed'
    args = {key: [object()]}
    assert CliApp.run(Settings, cli_args=args, cli_settings_source=source).fixed == [1]
    assert key in args


def test_unmarked_field_still_decodes(env):
    class Settings(BaseSettings):
        fixed: Annotated[list[int], NoExternalSources] = [1]
        ordinary: list[int] = []

    env.set('ORDINARY', 'invalid')
    from pydantic_settings import SettingsError

    with pytest.raises(SettingsError, match='ordinary'):
        Settings()
