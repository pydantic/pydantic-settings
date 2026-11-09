"""File priority must be applied to the field names accepted by the settings model."""

import json

import pytest
from pydantic import AliasChoices, BaseModel, Field

from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
    YamlConfigSettingsSource,
)


def _toml_value(value):
    if isinstance(value, dict):
        return '{' + ', '.join(f'{json.dumps(key)} = {_toml_value(item)}' for key, item in value.items()) + '}'
    return json.dumps(value)


@pytest.fixture(params=['json', 'toml', 'yaml'])
def load_files(request, tmp_path):
    kind = request.param
    source = {'json': JsonConfigSettingsSource, 'toml': TomlConfigSettingsSource, 'yaml': YamlConfigSettingsSource}[
        kind
    ]

    def load(settings_cls, values, *, deep_merge=False, source_options=None):
        paths = []
        for index, value in enumerate(values):
            path = tmp_path / f'{index}.{kind}'
            if kind == 'json':
                content = json.dumps(value)
            elif kind == 'toml':
                content = '\n'.join(f'{json.dumps(key)} = {_toml_value(item)}' for key, item in value.items())
            else:
                yaml = pytest.importorskip('yaml')
                content = yaml.safe_dump(value, sort_keys=False)
            path.write_text(content, encoding='utf-8')
            paths.append(path)

        class Settings(settings_cls):
            @classmethod
            def settings_customise_sources(cls, settings_cls, **kwargs):
                return (source(settings_cls, paths, deep_merge=deep_merge, **(source_options or {})),)

        return Settings()

    load.kind = kind
    return load


@pytest.mark.parametrize('deep_merge', [False, True])
@pytest.mark.parametrize('keys', [('token', 'token'), ('TOKEN', 'TOKEN'), ('TOKEN', 'token'), ('token', 'TOKEN')])
def test_later_file_wins_after_case_matching(load_files, deep_merge, keys):
    class Settings(BaseSettings):
        token: str
        model_config = SettingsConfigDict(case_sensitive=False)

    assert load_files(Settings, [{keys[0]: 'first'}, {keys[1]: 'second'}], deep_merge=deep_merge).token == 'second'


@pytest.mark.parametrize('deep_merge', [False, True])
def test_file_priority_with_nested_model(load_files, deep_merge):
    class Nested(BaseModel):
        first: int = 0
        second: int = 0

    class Settings(BaseSettings):
        nested: Nested

    settings = load_files(Settings, [{'NESTED': {'first': 1}}, {'nested': {'second': 2}}], deep_merge=deep_merge)
    assert settings.model_dump() == {'nested': {'first': 1 if deep_merge else 0, 'second': 2}}


@pytest.mark.parametrize('deep_merge', [False, True])
def test_file_priority_with_validation_alias(load_files, deep_merge):
    class Settings(BaseSettings):
        token: str = Field(validation_alias='ApiToken')

    assert (
        load_files(Settings, [{'APITOKEN': 'first'}, {'apitoken': 'second'}], deep_merge=deep_merge).token == 'second'
    )


@pytest.mark.parametrize('deep_merge', [False, True])
def test_distinct_alias_choices_keep_existing_priority(load_files, deep_merge):
    class Settings(BaseSettings):
        token: str = Field(validation_alias=AliasChoices('preferred', 'fallback'))

    assert (
        load_files(Settings, [{'preferred': 'first'}, {'fallback': 'second'}], deep_merge=deep_merge).token == 'first'
    )


def test_single_file_case_collision_keeps_first_key(load_files):
    class Settings(BaseSettings):
        token: str

    assert load_files(Settings, [{'TOKEN': 'first', 'token': 'second'}]).token == 'first'


def test_single_file_alias_choices_keep_alias_priority(load_files):
    class Settings(BaseSettings):
        token: str = Field(validation_alias=AliasChoices('preferred', 'fallback'))

    assert load_files(Settings, [{'fallback': 'first', 'preferred': 'second'}]).token == 'second'


@pytest.mark.parametrize('deep_merge', [False, True])
def test_case_sensitive_files_keep_distinct_fields(load_files, deep_merge):
    class Settings(BaseSettings):
        TOKEN: str
        token: str
        model_config = SettingsConfigDict(case_sensitive=True)

    assert load_files(Settings, [{'TOKEN': 'first'}, {'token': 'second'}], deep_merge=deep_merge).model_dump() == {
        'TOKEN': 'first',
        'token': 'second',
    }


@pytest.mark.parametrize('deep_merge', [False, True])
def test_dictionary_values_keep_case_sensitive_keys(load_files, deep_merge):
    class Settings(BaseSettings):
        tokens: dict[str, str]

    settings = load_files(
        Settings, [{'TOKENS': {'USER': 'first'}}, {'tokens': {'user': 'second'}}], deep_merge=deep_merge
    )
    assert settings.tokens == ({'USER': 'first', 'user': 'second'} if deep_merge else {'user': 'second'})


@pytest.mark.parametrize('deep_merge', [False, True])
def test_selected_sections_keep_file_priority(load_files, deep_merge):
    if load_files.kind == 'json':
        pytest.skip('JSON sources do not select sections')

    class Settings(BaseSettings):
        token: str

    options = (
        {'toml_table_header': ('outer', 'settings')}
        if load_files.kind == 'toml'
        else {'yaml_config_section': 'outer.settings'}
    )
    settings = load_files(
        Settings,
        [{'outer': {'settings': {'TOKEN': 'first'}}}, {'outer': {'settings': {'token': 'second'}}}],
        deep_merge=deep_merge,
        source_options=options,
    )
    assert settings.token == 'second'


def test_shallow_parent_replacement_still_removes_section(load_files):
    if load_files.kind == 'json':
        pytest.skip('JSON sources do not select sections')

    class Settings(BaseSettings):
        token: str = 'default'

    options = (
        {'toml_table_header': ('outer', 'settings')}
        if load_files.kind == 'toml'
        else {'yaml_config_section': 'outer.settings'}
    )
    with pytest.raises(KeyError):
        load_files(
            Settings, [{'outer': {'settings': {'TOKEN': 'first'}}}, {'outer': {'other': 1}}], source_options=options
        )


def test_yaml_literal_section_path_keeps_precedence(load_files):
    if load_files.kind != 'yaml':
        pytest.skip('YAML literal-dot section selection')

    class Settings(BaseSettings):
        token: str

    settings = load_files(
        Settings,
        [
            {'outer.settings': {'TOKEN': 'first'}},
            {'outer.settings': {'token': 'second'}, 'outer': {'settings': {'token': 'ignored'}}},
        ],
        source_options={'yaml_config_section': 'outer.settings'},
    )
    assert settings.token == 'second'


@pytest.mark.parametrize('source', [JsonConfigSettingsSource, TomlConfigSettingsSource, YamlConfigSettingsSource])
def test_legacy_read_files_override(source):
    class CustomSource(source):
        def _read_files(self, files, deep_merge=False):
            return {'TOKEN': 'custom'}

    class Settings(BaseSettings):
        token: str

        @classmethod
        def settings_customise_sources(cls, settings_cls, **kwargs):
            return (CustomSource(settings_cls),)

    assert Settings().token == 'custom'


@pytest.mark.parametrize('deep_merge', [False, True])
@pytest.mark.parametrize('split_files', [False, True])
def test_overlapping_alias_choices_normalize_only_once(load_files, deep_merge, split_files):
    class Settings(BaseSettings):
        first: str = Field(validation_alias=AliasChoices('a', 'b'))
        second: str = Field(validation_alias=AliasChoices('b', 'c'))

    values = [{'A': 'first'}, {'C': 'second'}] if split_files else [{'A': 'first', 'C': 'second'}]
    assert load_files(Settings, values, deep_merge=deep_merge).model_dump() == {'first': 'first', 'second': 'second'}


@pytest.mark.parametrize('deep_merge', [False, True])
def test_unaccepted_field_names_are_not_case_folded(load_files, deep_merge):
    class Settings(BaseSettings):
        token: str = Field(validation_alias='ApiToken')
        model_config = SettingsConfigDict(validate_by_name=False, extra='allow')

    settings = load_files(
        Settings, [{'ApiToken': 'value', 'TOKEN': 'first'}, {'token': 'second'}], deep_merge=deep_merge
    )
    assert settings.token == 'value'
    assert settings.model_extra == {'TOKEN': 'first', 'token': 'second'}


@pytest.mark.parametrize('deep_merge', [False, True])
@pytest.mark.parametrize(
    'config',
    [
        SettingsConfigDict(validate_by_alias=False),
        SettingsConfigDict(validate_by_name=True),
        SettingsConfigDict(populate_by_name=True),
    ],
)
def test_accepted_field_names_with_alias(load_files, deep_merge, config):
    class Settings(BaseSettings):
        token: str = Field(validation_alias='ApiToken')
        model_config = config

    assert load_files(Settings, [{'TOKEN': 'first'}, {'token': 'second'}], deep_merge=deep_merge).token == 'second'


@pytest.mark.parametrize('deep_merge', [False, True])
def test_disabled_aliases_remain_literal_extras(load_files, deep_merge):
    class Settings(BaseSettings):
        token: str = Field(validation_alias='ApiToken')
        model_config = SettingsConfigDict(validate_by_alias=False, extra='allow')

    settings = load_files(
        Settings,
        [{'TOKEN': 'first', 'APITOKEN': 'extra-first'}, {'token': 'second', 'apitoken': 'extra-second'}],
        deep_merge=deep_merge,
    )
    assert settings.token == 'second'
    assert settings.model_extra == {'APITOKEN': 'extra-first', 'apitoken': 'extra-second'}


@pytest.mark.parametrize('deep_merge', [False, True])
def test_validate_by_name_overrides_populate_by_name(load_files, deep_merge):
    class Settings(BaseSettings):
        token: str = Field(validation_alias='ApiToken')
        model_config = SettingsConfigDict(populate_by_name=True, validate_by_name=False, extra='allow')

    settings = load_files(
        Settings,
        [{'ApiToken': 'value', 'TOKEN': 'first'}, {'token': 'second'}],
        deep_merge=deep_merge,
    )
    assert settings.token == 'value'
    assert settings.model_extra == {'TOKEN': 'first', 'token': 'second'}


@pytest.mark.parametrize('deep_merge', [False, True])
def test_alias_keeps_priority_over_accepted_name(load_files, deep_merge):
    class Settings(BaseSettings):
        token: str = Field(validation_alias='ApiToken')
        model_config = SettingsConfigDict(validate_by_name=True)

    assert load_files(Settings, [{'ApiToken': 'first'}, {'TOKEN': 'second'}], deep_merge=deep_merge).token == 'first'


@pytest.mark.parametrize('deep_merge', [False, True])
def test_alias_path_top_level_case_precedence(load_files, deep_merge):
    from pydantic import AliasPath

    class Settings(BaseSettings):
        token: str = Field(validation_alias=AliasPath('Payload', 'Token'))

    assert (
        load_files(
            Settings, [{'PAYLOAD': {'Token': 'first'}}, {'payload': {'Token': 'second'}}], deep_merge=deep_merge
        ).token
        == 'second'
    )


@pytest.mark.parametrize('deep_merge', [False, True])
def test_validation_alias_does_not_fold_serialization_alias_or_extras(load_files, deep_merge):
    class Settings(BaseSettings):
        token: str = Field(alias='Output', validation_alias='Input')
        model_config = SettingsConfigDict(extra='allow')

    settings = load_files(
        Settings,
        [{'INPUT': 'first', 'OUTPUT': 1, 'EXTRA': 2}, {'input': 'second', 'output': 3, 'extra': 4}],
        deep_merge=deep_merge,
    )
    assert settings.token == 'second'
    assert settings.model_extra == {'OUTPUT': 1, 'EXTRA': 2, 'output': 3, 'extra': 4}


@pytest.mark.parametrize('deep_merge', [False, True])
def test_nested_model_fields_are_not_case_folded(load_files, deep_merge):
    class Nested(BaseModel):
        Token: str = 'default'
        token: str = 'default'

    class Settings(BaseSettings):
        nested: Nested

    settings = load_files(
        Settings, [{'NESTED': {'Token': 'first'}}, {'nested': {'token': 'second'}}], deep_merge=deep_merge
    )
    assert settings.nested.model_dump() == {'Token': 'first' if deep_merge else 'default', 'token': 'second'}


@pytest.mark.parametrize('deep_merge', [False, True])
def test_section_missing_from_earlier_file(load_files, deep_merge):
    if load_files.kind == 'json':
        pytest.skip('JSON sources do not select sections')

    class Settings(BaseSettings):
        token: str

    options = (
        {'toml_table_header': ('outer', 'settings')}
        if load_files.kind == 'toml'
        else {'yaml_config_section': 'outer.settings'}
    )
    settings = load_files(
        Settings,
        [{'outer': {'other': 1}}, {'outer': {'settings': {'TOKEN': 'value'}}}],
        deep_merge=deep_merge,
        source_options=options,
    )
    assert settings.token == 'value'
