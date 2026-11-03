"""AI-assisted preservation controls for JSON lists in model unions."""

import json

import pytest
from pydantic import BaseModel

from pydantic_settings import BaseSettings, SettingsConfigDict


@pytest.mark.parametrize('items', [[], ['single'], ['café', 'one,two', '雪']])
@pytest.mark.parametrize('model_tags', ['["unused"]', 'not-json'])
def test_json_list_ignores_nested_fields_of_unused_union_model(
    monkeypatch: pytest.MonkeyPatch, items: list[str], model_tags: str
) -> None:
    class ModelAlternative(BaseModel):
        tags: list[str]

    class Settings(BaseSettings):
        value: list[str] | ModelAlternative

        model_config = SettingsConfigDict(env_prefix='UNION_EDGE_', env_nested_delimiter='__')

    monkeypatch.setenv('UNION_EDGE_VALUE', json.dumps(items, ensure_ascii=False))
    # This name addresses the model alternative, not an index of the selected list.
    monkeypatch.setenv('UNION_EDGE_VALUE__TAGS', model_tags)

    settings = Settings()

    assert settings.value == items
    assert settings.model_dump() == {'value': items}
