"""External CLI separators preserve internal settings paths."""

import argparse

import pytest
from pydantic import AliasChoices, AliasPath, BaseModel, Field

from pydantic_settings import BaseSettings, CliApp, SettingsConfigDict, SettingsError
from pydantic_settings.sources import CliImplicitFlag, CliMutuallyExclusiveGroup, CliSettingsSource, CliSubCommand


@pytest.mark.parametrize('delimiter', ['.', '-', '__', '::', 'X', '--'])
def test_nested_delimiter_argv_help_and_serialization(delimiter):
    class Leaf(BaseModel):
        value: int = 0

    class Nested(BaseModel):
        leaf: Leaf = Leaf()

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(cli_nested_delimiter=delimiter)
        nested: Nested = Nested()

    option = f'--nested{delimiter}leaf{delimiter}value'
    instance = CliApp.run(Settings, cli_args=[option, '7'])
    assert instance.nested.leaf.value == 7
    assert option in CliApp.format_help(Settings)
    serialized = CliApp.serialize(instance)
    assert serialized == [option, '7']
    assert CliApp.run(Settings, cli_args=serialized) == instance


def test_runtime_override_and_environment_names(monkeypatch):
    class Nested(BaseModel):
        value: int = 0

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_nested_delimiter='__', cli_nested_delimiter=':')
        nested: Nested = Nested()

    monkeypatch.setenv('NESTED__VALUE', '9')
    assert Settings().nested.value == 9
    assert Settings(_cli_parse_args=['--nested-value', '4'], _cli_nested_delimiter='-').nested.value == 4
    assert Settings(_cli_parse_args=['--nested:value', '5']).nested.value == 5
    assert Settings().nested.value == 9


def test_structural_prefix_and_literal_alias_dots():
    class Nested(BaseModel):
        value: int = 0
        dotted: int = Field(0, alias='literal.dot')

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(cli_nested_delimiter='__', cli_prefix='app.service')
        nested: Nested = Nested()
        other: str = Field('', alias='other.dot')

    args = ['--app__service__nested__value', '3', '--app__service__other.dot', 'text']
    instance = CliApp.run(Settings, cli_args=args)
    assert instance.nested.value == 3
    assert instance.other == 'text'
    help_text = CliApp.format_help(Settings)
    assert args[0] in help_text and args[2] in help_text
    assert '--app__service__nested__literal.dot' in help_text
    assert CliApp.run(Settings, cli_args=CliApp.serialize(instance)) == instance


def test_subcommand_and_boolean_mutual_exclusion():
    class Batch(CliMutuallyExclusiveGroup):
        add: CliImplicitFlag[bool] = False
        delete: CliImplicitFlag[bool] = False

    class Edit(BaseModel):
        batch: Batch = Batch()

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(cli_nested_delimiter='-', cli_exit_on_error=False)
        edit: CliSubCommand[Edit]

    instance = CliApp.run(Settings, cli_args=['edit', '--batch-add'])
    assert instance.edit.batch.add
    assert not instance.edit.batch.delete
    assert CliApp.run(Settings, cli_args=CliApp.serialize(instance)) == instance
    with pytest.raises(SettingsError, match='not allowed with argument'):
        CliApp.run(Settings, cli_args=['edit', '--batch-add', '--batch-delete'])


def test_custom_parser_shortcuts_and_literal_shortcut_names():
    class Nested(BaseModel):
        value: str = ''

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(
            cli_nested_delimiter='__', cli_shortcuts={'nested__value': ['v', 'literal.shortcut']}
        )
        nested: Nested = Nested()

    parser = argparse.ArgumentParser()
    source = CliSettingsSource(Settings, root_parser=parser)
    assert '--nested__value' in parser.format_help()
    assert '--literal.shortcut' in parser.format_help()
    instance = CliApp.run(Settings, cli_args=['--literal.shortcut', 'yes'], cli_settings_source=source)
    assert instance.nested.value == 'yes'
    assert CliApp.run(Settings, cli_args=['-v', 'short']).nested.value == 'short'


@pytest.mark.parametrize('delimiter', ['', ' ', '\t', '\n', '\x00', '=', 'a=b', 1, False, []])
def test_invalid_nested_delimiter(delimiter):
    class Settings(BaseSettings):
        value: str = ''

    with pytest.raises(SettingsError, match='delimiter'):
        CliSettingsSource(Settings, cli_nested_delimiter=delimiter)


@pytest.mark.parametrize('nested_first', [False, True])
def test_separator_collision_is_reported(nested_first):
    class Nested(BaseModel):
        value: int = 0

    if nested_first:

        class Settings(BaseSettings):
            model_config = SettingsConfigDict(cli_nested_delimiter='__')
            nested: Nested = Nested()
            flat: int = Field(0, alias='nested__value')
    else:

        class Settings(BaseSettings):
            model_config = SettingsConfigDict(cli_nested_delimiter='__')
            flat: int = Field(0, alias='nested__value')
            nested: Nested = Nested()

    with pytest.raises(SettingsError, match='ambiguous'):
        CliSettingsSource(Settings)


def test_kebab_case_and_structural_prefix():
    class Nested(BaseModel):
        my_value: int = 0

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(cli_nested_delimiter='__', cli_prefix='app_name.group', cli_kebab_case=True)
        my_nested: Nested = Nested()

    option = '--app-name__group__my-nested__my-value'
    instance = CliApp.run(Settings, cli_args=[option, '8'])
    assert instance.my_nested.my_value == 8
    assert option in CliApp.format_help(Settings)
    assert CliApp.serialize(instance) == [option, '8']


def test_required_option_and_default_separator_unchanged():
    class Nested(BaseModel):
        value: int

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(cli_nested_delimiter='__', cli_enforce_required=True, cli_exit_on_error=False)
        nested: Nested

    with pytest.raises(SettingsError, match='required'):
        CliApp.run(Settings, cli_args=[])
    assert CliApp.run(Settings, cli_args=['--nested__value', '4']).nested.value == 4

    class DefaultSettings(BaseSettings):
        nested: Nested

    assert CliApp.run(DefaultSettings, cli_args=['--nested.value', '4']).nested.value == 4


@pytest.mark.parametrize(
    'delimiter,kebab_case,option', [('__', False, '--nested__token_list'), ('-', True, '--nested-token-list')]
)
def test_nested_alias_path_option_uses_external_separator(delimiter, kebab_case, option):
    class Nested(BaseModel):
        first: str = Field('first', validation_alias=AliasPath('token_list', 0))
        second: str = Field('second', validation_alias=AliasPath('token_list', 1))

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(cli_nested_delimiter=delimiter, cli_kebab_case=kebab_case)
        nested: Nested = Nested()

    instance = CliApp.run(Settings, cli_args=[option, '["a", "b"]'])
    assert instance.nested.first == 'a'
    assert instance.nested.second == 'b'
    assert option in CliApp.format_help(Settings)
    assert CliApp.run(Settings, cli_args=CliApp.serialize(instance)) == instance


@pytest.mark.parametrize('delimiter', ['.', '__'])
def test_shared_literal_choice_keeps_existing_first_match(delimiter):
    class Settings(BaseSettings):
        model_config = SettingsConfigDict(cli_nested_delimiter=delimiter)
        first: str = Field('one', validation_alias=AliasChoices('first', 'shared'))
        second: str = Field('two', validation_alias=AliasChoices('second', 'shared'))

    assert CliApp.run(Settings, cli_args=['--shared', 'chosen']).model_dump() == {'first': 'chosen', 'second': 'two'}


def test_default_alias_path_spelling_keeps_existing_behavior():
    class Nested(BaseModel):
        value: str = Field('', validation_alias=AliasPath('token_list', 0))

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(cli_kebab_case=True)
        child: Nested = Nested()

    instance = CliApp.run(Settings, cli_args=['--child.token_list', '["text"]'])
    assert instance.child.value == 'text'
    assert '--child.token_list' in CliApp.format_help(Settings)
    # Preserve the existing default serializer spelling; custom delimiters do
    # not change this older mismatch between AliasPath parsing and serialization.
    assert CliApp.serialize(instance) == ['--child.token-list', '["text"]']


@pytest.mark.parametrize('delimiter', ['.', '__'])
def test_alias_destination_binding_is_unchanged(delimiter):
    class Settings(BaseSettings):
        model_config = SettingsConfigDict(cli_nested_delimiter=delimiter)
        first: str = Field('one', validation_alias='aa')
        second: str = Field('two', validation_alias=AliasChoices('aa', 'bb'))
        bb: str = 'three'

    assert CliApp.run(Settings, cli_args=['--bb', 'chosen']).model_dump() == {
        'first': 'chosen',
        'second': 'chosen',
        'bb': 'chosen',
    }


def test_default_hyphenated_alias_path_keeps_parser_destination_inference():
    class Nested(BaseModel):
        value: str = Field('', validation_alias=AliasPath('token-list', 0))

    class Settings(BaseSettings):
        child: Nested = Nested()

    # Preserve existing argparse destination inference rather than repair it.
    assert CliApp.run(Settings, cli_args=['--child.token-list', '["chosen"]']).child.value == ''


@pytest.mark.parametrize('delimiter', ['.', '__'])
@pytest.mark.parametrize('reverse_fields', [False, True])
@pytest.mark.parametrize('unknown_args', [False, True])
def test_nested_delimiter_non_option_names_do_not_collide(delimiter, reverse_fields, unknown_args):
    from pydantic import create_model

    from pydantic_settings import CliPositionalArg, CliUnknownArgs

    class Nested(BaseModel):
        value: int = 0

    fields = {
        'nested__value': (CliUnknownArgs if unknown_args else CliPositionalArg[str], ...),
        'nested': (Nested, Nested()),
    }
    if reverse_fields:
        fields = dict(reversed(list(fields.items())))
    Settings = create_model(
        'Settings',
        __base__=BaseSettings,
        __config__=SettingsConfigDict(cli_nested_delimiter=delimiter, cli_ignore_unknown_args=unknown_args),
        **fields,
    )
    option = f'--nested{delimiter}value'
    instance = CliApp.run(Settings, cli_args=['item', option, '7'])
    assert instance.nested.value == 7
    assert instance.nested__value == (['item'] if unknown_args else 'item')
    assert option in CliApp.format_help(Settings)
    assert CliApp.run(Settings, cli_args=CliApp.serialize(instance)) == instance
