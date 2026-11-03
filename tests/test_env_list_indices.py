import pytest
from pydantic import BaseModel, Field

from pydantic_settings import BaseSettings, SettingsConfigDict


def test_indexed_env_variable_updates_model_list_item(monkeypatch: pytest.MonkeyPatch) -> None:
    class Item(BaseModel):
        field: str
        count: int

    class Settings(BaseSettings):
        my_obj_list: list[Item] = Field(default_factory=list)

        model_config = SettingsConfigDict(env_prefix='INDEXED_', env_nested_delimiter='__')

    monkeypatch.setenv(
        'INDEXED_MY_OBJ_LIST',
        '[{"field":"first","count":1},{"field":"second","count":2},{"field":"third","count":3}]',
    )
    original = [
        {'field': 'first', 'count': 1},
        {'field': 'second', 'count': 2},
        {'field': 'third', 'count': 3},
    ]
    assert Settings().model_dump()['my_obj_list'] == original

    monkeypatch.setenv('INDEXED_MY_OBJ_LIST__2__FIELD', 'changed')

    assert Settings().model_dump()['my_obj_list'] == [
        original[0],
        original[1],
        {'field': 'changed', 'count': 3},
    ]
