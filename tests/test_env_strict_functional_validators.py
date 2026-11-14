from typing import Annotated, Any

import pytest
from annotated_types import Le
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    Field,
    PlainValidator,
    Strict,
    StrictInt,
    StringConstraints,
    ValidationError,
    WrapValidator,
)
from typing_extensions import TypeAliasType

from pydantic_settings import BaseSettings, SettingsConfigDict


@pytest.mark.parametrize('optional', [False, True])
@pytest.mark.parametrize('source', ['env', 'dotenv', 'nested_env'])
def test_strict_source_runs_after_validator_once(optional, source, env, tmp_path):
    calls = []

    def increment(value: Any) -> int:
        calls.append(value)
        return int(value) + 1

    annotation = Annotated[int, AfterValidator(increment)]
    if optional:
        annotation = annotation | None

    class Settings(BaseSettings):
        value: annotation
        model_config = SettingsConfigDict(strict=True)

    if source == 'nested_env':

        class SubModel(BaseModel):
            value: annotation

        class NestedSettings(BaseSettings):
            sub: SubModel
            model_config = SettingsConfigDict(strict=True, env_nested_delimiter='__')

        env.set('SUB__VALUE', '1')
        value = NestedSettings().sub.value
    elif source == 'dotenv':
        path = tmp_path / '.env'
        path.write_text('VALUE=1\n', encoding='utf-8')
        value = Settings(_env_file=path).value
    else:
        env.set('VALUE', '1')
        value = Settings().value

    assert value == 2
    assert len(calls) == 1


@pytest.mark.parametrize('raw, expected, expected_calls', [('1', 11, ['even', 'fallback']), ('2', 2, ['even'])])
def test_strict_union_still_selects_a_branch_using_its_validators(env, raw, expected, expected_calls):
    calls = []

    def require_even(value: int) -> int:
        calls.append('even')
        if value % 2:
            raise ValueError('not even')
        return value

    def fallback(value: int) -> int:
        calls.append('fallback')
        return value + 10

    class Settings(BaseSettings):
        value: Annotated[int, AfterValidator(require_even)] | Annotated[int, AfterValidator(fallback)] | None
        model_config = SettingsConfigDict(strict=True)

    env.set('VALUE', raw)
    assert Settings().value == expected
    assert calls == expected_calls


def test_strict_source_preserves_annotated_constraints(env):
    class Settings(BaseSettings):
        value: Annotated[int, Field(gt=0), AfterValidator(lambda value: value + 1)] | None
        model_config = SettingsConfigDict(strict=True)

    env.set('VALUE', '1')
    assert Settings().value == 2
    env.set('VALUE', '-1')
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize('optional', [False, True, 'wrapped'])
@pytest.mark.parametrize('raw, expected', [('11', 10), ('9', 9)])
@pytest.mark.parametrize('constraint', [Field(le=10), Le(10)])
def test_after_validator_can_transform_before_a_later_constraint(env, optional, raw, expected, constraint):
    number = TypeAliasType('Number', Annotated[int, AfterValidator(lambda value: min(value, 10)), constraint])
    annotation = number | None if optional else number
    if optional == 'wrapped':
        annotation = TypeAliasType('Wrapped', Annotated[annotation, Field(le=10)])

    class Settings(BaseSettings):
        value: annotation
        model_config = SettingsConfigDict(strict=True)

    env.set('VALUE', raw)
    assert Settings().value == expected


@pytest.mark.parametrize('union', ['none', 'optional', 'float', 'annotated_union'])
@pytest.mark.parametrize('kind', ['before', 'plain', 'wrap'])
def test_early_validator_retains_its_existing_input_coercion(env, union, kind):
    def convert(value):
        return int(value) + 10 if isinstance(value, str) else value

    def wrap(value, handler):
        return handler(convert(value))

    validator = {'before': BeforeValidator(convert), 'plain': PlainValidator(convert), 'wrap': WrapValidator(wrap)}[
        kind
    ]
    number = TypeAliasType('Number', Annotated[int, validator])
    annotation = number if union == 'none' else number | (None if union == 'optional' else float)
    if union == 'annotated_union':
        annotation = TypeAliasType('Wrapped', Annotated[number | None, 'units'])

    class Settings(BaseSettings):
        value: annotation
        model_config = SettingsConfigDict(strict=True)

    env.set('VALUE', '1')
    assert Settings().value == 11


@pytest.mark.parametrize('strict_mode', ['type', 'field', 'metadata'])
def test_after_validator_preserves_strict_integer_boolean_rejection(env, strict_mode):
    after = AfterValidator(lambda value: value + 1)
    strict_number = {
        'type': Annotated[StrictInt, after],
        'field': Annotated[int, after, Field(strict=True)],
        'metadata': Annotated[int, after, Strict()],
    }[strict_mode]

    class Settings(BaseSettings):
        value: strict_number | None
        model_config = SettingsConfigDict(strict=True)

    env.set('VALUE', 'true')
    with pytest.raises(ValidationError):
        Settings()
    env.set('VALUE', '1')
    assert Settings().value == 2


def test_after_validator_with_grouped_string_constraints(env):
    number = TypeAliasType(
        'Number', Annotated[str, AfterValidator(lambda value: value + '!'), StringConstraints(max_length=4)]
    )

    class Settings(BaseSettings):
        value: number
        model_config = SettingsConfigDict(strict=True)

    env.set('VALUE', 'abc')
    assert Settings().value == 'abc!'


def test_after_validator_preserves_unrelated_metadata(env):
    class Settings(BaseSettings):
        value: Annotated[int, AfterValidator(lambda value: value + 1), 'units'] | None
        model_config = SettingsConfigDict(strict=True)

    env.set('VALUE', '1')
    assert Settings().value == 2
