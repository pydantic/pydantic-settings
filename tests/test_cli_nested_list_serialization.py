from typing import Any, Literal

import pytest
from pydantic import BaseModel

from pydantic_settings import CliApp


@pytest.mark.parametrize('list_style', ['json', 'argparse', 'lazy'])
@pytest.mark.parametrize(
    'values',
    [
        {'objects': [{'x': 1}, {'x': 2}]},
        {'arrays': [['a,b', ' spaced '], ['second']]},
        {'flags': [{'enabled': True, 'missing': None}]},
        {'records': [{'counts': [1, 2]}, {'counts': []}]},
    ],
)
def test_nested_list_items_round_trip(values: dict[str, Any], list_style: Literal['json', 'argparse', 'lazy']) -> None:
    class Settings(BaseModel):
        objects: list[dict[str, int]] = []
        arrays: list[list[str]] = []
        flags: list[dict[str, bool | None]] = []
        records: list[dict[str, list[int]]] = []

    settings = Settings(**values)
    args = CliApp.serialize(settings, list_style=list_style)

    assert CliApp.run(Settings, cli_args=args, cli_exit_on_error=False) == settings
    assert args == CliApp.serialize(settings, list_style='json')


@pytest.mark.parametrize(
    'list_style, expected',
    [
        ('json', ['--numbers', '[1, 2]', '--names', '["hello world", "O\'Reilly"]']),
        ('argparse', ['--numbers', '1', '--numbers', '2', '--names', 'hello world', '--names', "O'Reilly"]),
        ('lazy', ['--numbers', '1,2', '--names', "hello world,O'Reilly"]),
    ],
)
def test_primitive_list_styles_keep_their_format(
    list_style: Literal['json', 'argparse', 'lazy'], expected: list[str]
) -> None:
    class Settings(BaseModel):
        numbers: list[int]
        names: list[str]

    settings = Settings(numbers=[1, 2], names=['hello world', "O'Reilly"])
    args = CliApp.serialize(settings, list_style=list_style)

    assert args == expected
    assert CliApp.run(Settings, cli_args=args, cli_exit_on_error=False) == settings
