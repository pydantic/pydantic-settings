from typing import Any, Literal, TypeVar

from pydantic import Json, RootModel
from typing_extensions import TypeAliasType

from pydantic_settings.sources.base import _unwrap_optional_annotation
from pydantic_settings.sources.types import SecretVersion
from pydantic_settings.sources.utils import (
    _annotation_contains_types,
    _annotation_is_complex,
    _resolve_type_alias,
    _substitute_typevars,
)
from pydantic_settings.utils import path_type_label


def test_path_type_label(tmp_path):
    result = path_type_label(tmp_path)
    assert result == 'directory'


T = TypeVar('T')


def test_substitute_typevars_without_matching_typevars():
    """An annotation with no substitutable TypeVars is returned unchanged."""
    assert _substitute_typevars(list[int], {T: str}) == list[int]
    # A bare (unparameterized) type has no args and is returned as-is.
    assert _substitute_typevars(int, {T: str}) is int


def test_substitute_typevars_union_reconstruction():
    """`X | Y` is not subscriptable, so substitution rebuilds it with `|`."""
    assert _substitute_typevars(T | None, {T: int}) == (int | None)


def test_resolve_type_alias_parameterized_without_type_args():
    """A parameterized alias used bare resolves to its underlying value."""
    IntOrT = TypeAliasType('IntOrT', int | T, type_params=(T,))

    assert _resolve_type_alias(IntOrT) == (int | T)
    assert _resolve_type_alias(IntOrT[str]) == (int | str)


def test_resolve_type_alias_passthrough():
    """Non-alias annotations are returned unchanged."""
    assert _resolve_type_alias(int) is int
    assert _resolve_type_alias(list[int]) == list[int]


def test_annotation_contains_types_collect_origin():
    """`collect` gathers matching annotations instead of short-circuiting."""
    tags: set[Any] = set()

    assert _annotation_contains_types(Literal['a', 'b'], (Literal,), collect=tags) is False
    assert tags == {Literal['a', 'b']}


def test_annotation_contains_types_collect_nested_origin():
    """Matches nested inside a union are collected too."""
    tags: set[Any] = set()

    assert _annotation_contains_types(Literal['a'] | None, (Literal,), collect=tags) is False
    assert tags == {Literal['a']}


def test_annotation_contains_types_collect_exact_match():
    """An annotation that *is* one of `types` is collected and still returns True."""
    tags: set[Any] = set()

    assert _annotation_contains_types(int, (int,), collect=tags) is True
    assert tags == {int}


def test_annotation_contains_types_is_instance_collect():
    """`is_instance` matches are collected rather than short-circuiting."""
    tags: set[Any] = set()

    assert _annotation_contains_types(Json, (type(Json),), is_instance=True, collect=tags) is False
    assert tags == {Json}


def test_annotation_contains_types_is_instance_origin_collect():
    """`is_instance` matches on the *origin* are collected too.

    `list[int]` has `list` as its origin, which is an instance of `type`. Avoid
    `Annotated[...]` here: its origin is a class on Python 3.12 but a special form
    from 3.13 on, so `isinstance(origin, type)` is version dependent.
    """
    tags: set[Any] = set()

    assert _annotation_contains_types(list[int], (type,), is_instance=True, collect=tags) is False
    assert list[int] in tags


def test_annotation_contains_types_is_instance_origin_short_circuits():
    """Without `collect`, an `is_instance` origin match returns True immediately."""
    assert _annotation_contains_types(list[int], (type,), is_instance=True) is True


def test_unwrap_optional_annotation():
    """`T | None` unwraps to `T`, regardless of where `None` sits in the union."""
    assert _unwrap_optional_annotation(int | None) is int
    # `None` first still resolves to the non-None member.
    assert _unwrap_optional_annotation(None | int) is int


def test_unwrap_optional_annotation_passthrough():
    """Non-optional annotations are returned unchanged."""
    assert _unwrap_optional_annotation(int) is int
    assert _unwrap_optional_annotation(int | str) == (int | str)
    # A three-member union including None is not a plain `T | None`.
    assert _unwrap_optional_annotation(int | str | None) == (int | str | None)


def test_secret_version_repr():
    assert repr(SecretVersion('3')) == "SecretVersion('3')"


def test_annotation_is_complex_root_model_without_init_state():
    """`init_state` is optional; omitting it skips the incomplete-field warning check."""

    class MyRootModel(RootModel[list[int]]):
        pass

    assert _annotation_is_complex(MyRootModel, []) is True
