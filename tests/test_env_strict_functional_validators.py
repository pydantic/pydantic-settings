from typing import Annotated, Any

import pytest
from pydantic import AfterValidator, BaseModel, BeforeValidator, Field, ValidationError

from pydantic_settings import BaseSettings, SettingsConfigDict


@pytest.mark.parametrize('validator', [BeforeValidator, AfterValidator])
@pytest.mark.parametrize('optional', [False, True])
@pytest.mark.parametrize('source', ['env', 'dotenv', 'nested_env'])
def test_strict_source_runs_functional_validator_once(validator, optional, source, env, tmp_path):
    calls = []

    def increment(value: Any) -> int:
        calls.append(value)
        return int(value) + 1

    annotation = Annotated[int, validator(increment)]
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
