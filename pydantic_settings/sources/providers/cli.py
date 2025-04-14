"""Command-line interface settings source."""

from __future__ import annotations as _annotations

import json
import re
import shlex
import sys
import typing
from argparse import (
    SUPPRESS,
    ArgumentParser,
    BooleanOptionalAction,
    Namespace,
    RawDescriptionHelpFormatter,
    _SubParsersAction,
)
from collections import defaultdict
from collections.abc import Mapping, Sequence
from enum import Enum
from textwrap import dedent
from types import SimpleNamespace
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Callable,
    Generic,
    NoReturn,
    Optional,
    TypeVar,
    Union,
    cast,
    overload,
)

import typing_extensions
from pydantic import BaseModel
from pydantic._internal._repr import Representation
from pydantic._internal._utils import is_model_class
from pydantic.dataclasses import is_pydantic_dataclass
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined
from typing_extensions import get_args, get_origin
from typing_inspection import typing_objects
from typing_inspection.introspection import is_union_origin

from ...exceptions import SettingsError
from ...utils import _lenient_issubclass, _WithArgsTypes
from ..types import _CliExplicitFlag, _CliImplicitFlag, _CliPositionalArg, _CliSubCommand
from ..utils import (
    _annotation_contains_types,
    _annotation_enum_val_to_name,
    _get_alias_names,
    _get_model_fields,
    _is_function,
    _strip_annotated,
    parse_env_vars,
)
from .env import EnvSettingsSource

if TYPE_CHECKING:
    from pydantic_settings.main import BaseSettings


class _CliInternalArgParser(ArgumentParser):
    def __init__(self, cli_exit_on_error: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._cli_exit_on_error = cli_exit_on_error

    def error(self, message: str) -> NoReturn:
        if not self._cli_exit_on_error:
            raise SettingsError(f'error parsing CLI: {message}')
        super().error(message)


class CliMutuallyExclusiveGroup(BaseModel):
    pass


T = TypeVar('T')
CliSubCommand = Annotated[Union[T, None], _CliSubCommand]
CliPositionalArg = Annotated[T, _CliPositionalArg]
_CliBoolFlag = TypeVar('_CliBoolFlag', bound=bool)
CliImplicitFlag = Annotated[_CliBoolFlag, _CliImplicitFlag]
CliExplicitFlag = Annotated[_CliBoolFlag, _CliExplicitFlag]
CLI_SUPPRESS = SUPPRESS
CliSuppress = Annotated[T, CLI_SUPPRESS]


class CliSettingsSource(EnvSettingsSource, Generic[T]):
    """
    Source class for loading settings values from CLI.

    Note:
        A `CliSettingsSource` connects with a `root_parser` object by using the parser methods to add
        `settings_cls` fields as command line arguments. The `CliSettingsSource` internal parser representation
        is based upon the `argparse` parsing library, and therefore, requires the parser methods to support
        the same attributes as their `argparse` library counterparts.

    Args:
        cli_prog_name: The CLI program name to display in help text. Defaults to `None` if cli_parse_args is `None`.
            Otherwise, defaults to sys.argv[0].
        cli_parse_args: The list of CLI arguments to parse. Defaults to None.
            If set to `True`, defaults to sys.argv[1:].
        cli_parse_none_str: The CLI string value that should be parsed (e.g. "null", "void", "None", etc.) into `None`
            type(None). Defaults to "null" if cli_avoid_json is `False`, and "None" if cli_avoid_json is `True`.
        cli_hide_none_type: Hide `None` values in CLI help text. Defaults to `False`.
        cli_avoid_json: Avoid complex JSON objects in CLI help text. Defaults to `False`.
        cli_enforce_required: Enforce required fields at the CLI. Defaults to `False`.
        cli_use_class_docs_for_groups: Use class docstrings in CLI group help text instead of field descriptions.
            Defaults to `False`.
        cli_exit_on_error: Determines whether or not the internal parser exits with error info when an error occurs.
            Defaults to `True`.
        cli_prefix: Prefix for command line arguments added under the root parser. Defaults to "".
        cli_flag_prefix_char: The flag prefix character to use for CLI optional arguments. Defaults to '-'.
        cli_implicit_flags: Whether `bool` fields should be implicitly converted into CLI boolean flags.
            (e.g. --flag, --no-flag). Defaults to `False`.
        cli_ignore_unknown_args: Whether to ignore unknown CLI args and parse only known ones. Defaults to `False`.
        cli_kebab_case: CLI args use kebab case. Defaults to `False`.
        case_sensitive: Whether CLI "--arg" names should be read with case-sensitivity. Defaults to `True`.
            Note: Case-insensitive matching is only supported on the internal root parser and does not apply to CLI
            subcommands.
        root_parser: The root parser object.
        parse_args_method: The root parser parse args method. Defaults to `argparse.ArgumentParser.parse_args`.
        add_argument_method: The root parser add argument method. Defaults to `argparse.ArgumentParser.add_argument`.
        add_argument_group_method: The root parser add argument group method.
            Defaults to `argparse.ArgumentParser.add_argument_group`.
        add_parser_method: The root parser add new parser (sub-command) method.
            Defaults to `argparse._SubParsersAction.add_parser`.
        add_subparsers_method: The root parser add subparsers (sub-commands) method.
            Defaults to `argparse.ArgumentParser.add_subparsers`.
        formatter_class: A class for customizing the root parser help text. Defaults to `argparse.RawDescriptionHelpFormatter`.
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        cli_prog_name: str | None = None,
        cli_parse_args: bool | list[str] | tuple[str, ...] | None = None,
        cli_parse_none_str: str | None = None,
        cli_hide_none_type: bool | None = None,
        cli_avoid_json: bool | None = None,
        cli_enforce_required: bool | None = None,
        cli_use_class_docs_for_groups: bool | None = None,
        cli_exit_on_error: bool | None = None,
        cli_prefix: str | None = None,
        cli_flag_prefix_char: str | None = None,
        cli_implicit_flags: bool | None = None,
        cli_ignore_unknown_args: bool | None = None,
        cli_kebab_case: bool | None = None,
        case_sensitive: bool | None = True,
        root_parser: Any = None,
        parse_args_method: Callable[..., Any] | None = None,
        add_argument_method: Callable[..., Any] | None = ArgumentParser.add_argument,
        add_argument_group_method: Callable[..., Any] | None = ArgumentParser.add_argument_group,
        add_parser_method: Callable[..., Any] | None = _SubParsersAction.add_parser,
        add_subparsers_method: Callable[..., Any] | None = ArgumentParser.add_subparsers,
        formatter_class: Any = RawDescriptionHelpFormatter,
    ) -> None:
        self.cli_prog_name = (
            cli_prog_name if cli_prog_name is not None else settings_cls.model_config.get('cli_prog_name', sys.argv[0])
        )
        self.cli_hide_none_type = (
            cli_hide_none_type
            if cli_hide_none_type is not None
            else settings_cls.model_config.get('cli_hide_none_type', False)
        )
        self.cli_avoid_json = (
            cli_avoid_json if cli_avoid_json is not None else settings_cls.model_config.get('cli_avoid_json', False)
        )
        if not cli_parse_none_str:
            cli_parse_none_str = 'None' if self.cli_avoid_json is True else 'null'
        self.cli_parse_none_str = cli_parse_none_str
        self.cli_enforce_required = (
            cli_enforce_required
            if cli_enforce_required is not None
            else settings_cls.model_config.get('cli_enforce_required', False)
        )
        self.cli_use_class_docs_for_groups = (
            cli_use_class_docs_for_groups
            if cli_use_class_docs_for_groups is not None
            else settings_cls.model_config.get('cli_use_class_docs_for_groups', False)
        )
        self.cli_exit_on_error = (
            cli_exit_on_error
            if cli_exit_on_error is not None
            else settings_cls.model_config.get('cli_exit_on_error', True)
        )
        self.cli_prefix = cli_prefix if cli_prefix is not None else settings_cls.model_config.get('cli_prefix', '')
        self.cli_flag_prefix_char = (
            cli_flag_prefix_char
            if cli_flag_prefix_char is not None
            else settings_cls.model_config.get('cli_flag_prefix_char', '-')
        )
        self._cli_flag_prefix = self.cli_flag_prefix_char * 2
        if self.cli_prefix:
            if cli_prefix.startswith('.') or cli_prefix.endswith('.') or not cli_prefix.replace('.', '').isidentifier():  # type: ignore
                raise SettingsError(f'CLI settings source prefix is invalid: {cli_prefix}')
            self.cli_prefix += '.'
        self.cli_implicit_flags = (
            cli_implicit_flags
            if cli_implicit_flags is not None
            else settings_cls.model_config.get('cli_implicit_flags', False)
        )
        self.cli_ignore_unknown_args = (
            cli_ignore_unknown_args
            if cli_ignore_unknown_args is not None
            else settings_cls.model_config.get('cli_ignore_unknown_args', False)
        )
        self.cli_kebab_case = (
            cli_kebab_case if cli_kebab_case is not None else settings_cls.model_config.get('cli_kebab_case', False)
        )

        case_sensitive = case_sensitive if case_sensitive is not None else True
        if not case_sensitive and root_parser is not None:
            raise SettingsError('Case-insensitive matching is only supported on the internal root parser')

        super().__init__(
            settings_cls,
            env_nested_delimiter='.',
            env_parse_none_str=self.cli_parse_none_str,
            env_parse_enums=True,
            env_prefix=self.cli_prefix,
            case_sensitive=case_sensitive,
        )

        root_parser = (
            _CliInternalArgParser(
                cli_exit_on_error=self.cli_exit_on_error,
                prog=self.cli_prog_name,
                description=None if settings_cls.__doc__ is None else dedent(settings_cls.__doc__),
                formatter_class=formatter_class,
                prefix_chars=self.cli_flag_prefix_char,
                allow_abbrev=False,
            )
            if root_parser is None
            else root_parser
        )
        self._connect_root_parser(
            root_parser=root_parser,
            parse_args_method=parse_args_method,
            add_argument_method=add_argument_method,
            add_argument_group_method=add_argument_group_method,
            add_parser_method=add_parser_method,
            add_subparsers_method=add_subparsers_method,
            formatter_class=formatter_class,
        )

        if cli_parse_args not in (None, False):
            if cli_parse_args is True:
                cli_parse_args = sys.argv[1:]
            elif not isinstance(cli_parse_args, (list, tuple)):
                raise SettingsError(
                    f'cli_parse_args must be a list or tuple of strings, received {type(cli_parse_args)}'
                )
            self._load_env_vars(parsed_args=self._parse_args(self.root_parser, cli_parse_args))

    @overload
    def __call__(self) -> dict[str, Any]: ...

    @overload
    def __call__(self, *, args: list[str] | tuple[str, ...] | bool) -> CliSettingsSource[T]:
        """
        Parse and load the command line arguments list into the CLI settings source.

        Args:
            args:
                The command line arguments to parse and load. Defaults to `None`, which means do not parse
                command line arguments. If set to `True`, defaults to sys.argv[1:]. If set to `False`, does
                not parse command line arguments.

        Returns:
            CliSettingsSource: The object instance itself.
        """
        ...

    @overload
    def __call__(self, *, parsed_args: Namespace | SimpleNamespace | dict[str, Any]) -> CliSettingsSource[T]:
        """
        Loads parsed command line arguments into the CLI settings source.

        Note:
            The parsed args must be in `argparse.Namespace`, `SimpleNamespace`, or vars dictionary
            (e.g., vars(argparse.Namespace)) format.

        Args:
            parsed_args: The parsed args to load.

        Returns:
            CliSettingsSource: The object instance itself.
        """
        ...

    def __call__(
        self,
        *,
        args: list[str] | tuple[str, ...] | bool | None = None,
        parsed_args: Namespace | SimpleNamespace | dict[str, list[str] | str] | None = None,
    ) -> dict[str, Any] | CliSettingsSource[T]:
        if args is not None and parsed_args is not None:
            raise SettingsError('`args` and `parsed_args` are mutually exclusive')
        elif args is not None:
            if args is False:
                return self._load_env_vars(parsed_args={})
            if args is True:
                args = sys.argv[1:]
            return self._load_env_vars(parsed_args=self._parse_args(self.root_parser, args))
        elif parsed_args is not None:
            return self._load_env_vars(parsed_args=parsed_args)
        else:
            return super().__call__()

    @overload
    def _load_env_vars(self) -> Mapping[str, str | None]: ...

    @overload
    def _load_env_vars(self, *, parsed_args: Namespace | SimpleNamespace | dict[str, Any]) -> CliSettingsSource[T]:
        """
        Loads the parsed command line arguments into the CLI environment settings variables.

        Note:
            The parsed args must be in `argparse.Namespace`, `SimpleNamespace`, or vars dictionary
            (e.g., vars(argparse.Namespace)) format.

        Args:
            parsed_args: The parsed args to load.

        Returns:
            CliSettingsSource: The object instance itself.
        """
        ...

    def _load_env_vars(
        self, *, parsed_args: Namespace | SimpleNamespace | dict[str, list[str] | str] | None = None
    ) -> Mapping[str, str | None] | CliSettingsSource[T]:
        if parsed_args is None:
            return {}

        if isinstance(parsed_args, (Namespace, SimpleNamespace)):
            parsed_args = vars(parsed_args)

        selected_subcommands: list[str] = []
        for field_name, val in parsed_args.items():
            if isinstance(val, list):
                parsed_args[field_name] = self._merge_parsed_list(val, field_name)
            elif field_name.endswith(':subcommand') and val is not None:
                subcommand_name = field_name.split(':')[0] + val
                subcommand_dest = self._cli_subcommands[field_name][subcommand_name]
                selected_subcommands.append(subcommand_dest)

        for subcommands in self._cli_subcommands.values():
            for subcommand_dest in subcommands.values():
                if subcommand_dest not in selected_subcommands:
                    parsed_args[subcommand_dest] = self.cli_parse_none_str

        parsed_args = {
            key: val
            for key, val in parsed_args.items()
            if not key.endswith(':subcommand') and val is not PydanticUndefined
        }
        if selected_subcommands:
            last_selected_subcommand = max(selected_subcommands, key=len)
            if not any(field_name for field_name in parsed_args.keys() if f'{last_selected_subcommand}.' in field_name):
                parsed_args[last_selected_subcommand] = '{}'

        self.env_vars = parse_env_vars(
            cast(Mapping[str, str], parsed_args),
            self.case_sensitive,
            self.env_ignore_empty,
            self.cli_parse_none_str,
        )

        return self

    def _get_merge_parsed_list_types(
        self, parsed_list: list[str], field_name: str
    ) -> tuple[Optional[type], Optional[type]]:
        merge_type = self._cli_dict_args.get(field_name, list)
        if (
            merge_type is list
            or not is_union_origin(get_origin(merge_type))
            or not any(
                type_
                for type_ in get_args(merge_type)
                if type_ is not type(None) and get_origin(type_) not in (dict, Mapping)
            )
        ):
            inferred_type = merge_type
        else:
            inferred_type = list if parsed_list and (len(parsed_list) > 1 or parsed_list[0].startswith('[')) else str

        return merge_type, inferred_type

    def _merge_parsed_list(self, parsed_list: list[str], field_name: str) -> str:
        try:
            merged_list: list[str] = []
            is_last_consumed_a_value = False
            merge_type, inferred_type = self._get_merge_parsed_list_types(parsed_list, field_name)
            for val in parsed_list:
                if not isinstance(val, str):
                    # If val is not a string, it's from an external parser and we can ignore parsing the rest of the
                    # list.
                    break
                val = val.strip()
                if val.startswith('[') and val.endswith(']'):
                    val = val[1:-1].strip()
                while val:
                    val = val.strip()
                    if val.startswith(','):
                        val = self._consume_comma(val, merged_list, is_last_consumed_a_value)
                        is_last_consumed_a_value = False
                    else:
                        if val.startswith('{') or val.startswith('['):
                            val = self._consume_object_or_array(val, merged_list)
                        else:
                            try:
                                val = self._consume_string_or_number(val, merged_list, merge_type)
                            except ValueError as e:
                                if merge_type is inferred_type:
                                    raise e
                                merge_type = inferred_type
                                val = self._consume_string_or_number(val, merged_list, merge_type)
                        is_last_consumed_a_value = True
                if not is_last_consumed_a_value:
                    val = self._consume_comma(val, merged_list, is_last_consumed_a_value)

            if merge_type is str:
                return merged_list[0]
            elif merge_type is list:
                return f'[{",".join(merged_list)}]'
            else:
                merged_dict: dict[str, str] = {}
                for item in merged_list:
                    merged_dict.update(json.loads(item))
                return json.dumps(merged_dict)
        except Exception as e:
            raise SettingsError(f'Parsing error encountered for {field_name}: {e}')

    def _consume_comma(self, item: str, merged_list: list[str], is_last_consumed_a_value: bool) -> str:
        if not is_last_consumed_a_value:
            merged_list.append('""')
        return item[1:]

    def _consume_object_or_array(self, item: str, merged_list: list[str]) -> str:
        count = 1
        close_delim = '}' if item.startswith('{') else ']'
        for consumed in range(1, len(item)):
            if item[consumed] in ('{', '['):
                count += 1
            elif item[consumed] in ('}', ']'):
                count -= 1
                if item[consumed] == close_delim and count == 0:
                    merged_list.append(item[: consumed + 1])
                    return item[consumed + 1 :]
        raise SettingsError(f'Missing end delimiter "{close_delim}"')

    def _consume_string_or_number(self, item: str, merged_list: list[str], merge_type: type[Any] | None) -> str:
        consumed = 0 if merge_type is not str else len(item)
        is_find_end_quote = False
        while consumed < len(item):
            if item[consumed] == '"' and (consumed == 0 or item[consumed - 1] != '\\'):
                is_find_end_quote = not is_find_end_quote
            if not is_find_end_quote and item[consumed] == ',':
                break
            consumed += 1
        if is_find_end_quote:
            raise SettingsError('Mismatched quotes')
        val_string = item[:consumed].strip()
        if merge_type in (list, str):
            try:
                float(val_string)
            except ValueError:
                if val_string == self.cli_parse_none_str:
                    val_string = 'null'
                if val_string not in ('true', 'false', 'null') and not val_string.startswith('"'):
                    val_string = f'"{val_string}"'
            merged_list.append(val_string)
        else:
            key, val = (kv for kv in val_string.split('=', 1))
            if key.startswith('"') and not key.endswith('"') and not val.startswith('"') and val.endswith('"'):
                raise ValueError(f'Dictionary key=val parameter is a quoted string: {val_string}')
            key, val = key.strip('"'), val.strip('"')
            merged_list.append(json.dumps({key: val}))
        return item[consumed:]

    def _get_sub_models(self, model: type[BaseModel], field_name: str, field_info: FieldInfo) -> list[type[BaseModel]]:
        field_types: tuple[Any, ...] = (
            (field_info.annotation,) if not get_args(field_info.annotation) else get_args(field_info.annotation)
        )
        if self.cli_hide_none_type:
            field_types = tuple([type_ for type_ in field_types if type_ is not type(None)])

        sub_models: list[type[BaseModel]] = []
        for type_ in field_types:
            if _annotation_contains_types(type_, (_CliSubCommand,), is_include_origin=False):
                raise SettingsError(f'CliSubCommand is not outermost annotation for {model.__name__}.{field_name}')
            elif _annotation_contains_types(type_, (_CliPositionalArg,), is_include_origin=False):
                raise SettingsError(f'CliPositionalArg is not outermost annotation for {model.__name__}.{field_name}')
            if is_model_class(_strip_annotated(type_)) or is_pydantic_dataclass(_strip_annotated(type_)):
                sub_models.append(_strip_annotated(type_))
        return sub_models

    def _verify_cli_flag_annotations(self, model: type[BaseModel], field_name: str, field_info: FieldInfo) -> None:
        if _CliImplicitFlag in field_info.metadata:
            cli_flag_name = 'CliImplicitFlag'
        elif _CliExplicitFlag in field_info.metadata:
            cli_flag_name = 'CliExplicitFlag'
        else:
            return

        if field_info.annotation is not bool:
            raise SettingsError(f'{cli_flag_name} argument {model.__name__}.{field_name} is not of type bool')

    def _sort_arg_fields(self, model: type[BaseModel]) -> list[tuple[str, FieldInfo]]:
        positional_variadic_arg = []
        positional_args, subcommand_args, optional_args = [], [], []
        for field_name, field_info in _get_model_fields(model).items():
            if _CliSubCommand in field_info.metadata:
                if not field_info.is_required():
                    raise SettingsError(f'subcommand argument {model.__name__}.{field_name} has a default value')
                else:
                    alias_names, *_ = _get_alias_names(field_name, field_info)
                    if len(alias_names) > 1:
                        raise SettingsError(f'subcommand argument {model.__name__}.{field_name} has multiple aliases')
                    field_types = [type_ for type_ in get_args(field_info.annotation) if type_ is not type(None)]
                    for field_type in field_types:
                        if not (is_model_class(field_type) or is_pydantic_dataclass(field_type)):
                            raise SettingsError(
                                f'subcommand argument {model.__name__}.{field_name} has type not derived from BaseModel'
                            )
                subcommand_args.append((field_name, field_info))
            elif _CliPositionalArg in field_info.metadata:
                alias_names, *_ = _get_alias_names(field_name, field_info)
                if len(alias_names) > 1:
                    raise SettingsError(f'positional argument {model.__name__}.{field_name} has multiple aliases')
                is_append_action = _annotation_contains_types(
                    field_info.annotation, (list, set, dict, Sequence, Mapping), is_strip_annotated=True
                )
                if not is_append_action:
                    positional_args.append((field_name, field_info))
                else:
                    positional_variadic_arg.append((field_name, field_info))
            else:
                self._verify_cli_flag_annotations(model, field_name, field_info)
                optional_args.append((field_name, field_info))

        if positional_variadic_arg:
            if len(positional_variadic_arg) > 1:
                field_names = ', '.join([name for name, info in positional_variadic_arg])
                raise SettingsError(f'{model.__name__} has multiple variadic positional arguments: {field_names}')
            elif subcommand_args:
                field_names = ', '.join([name for name, info in positional_variadic_arg + subcommand_args])
                raise SettingsError(
                    f'{model.__name__} has variadic positional arguments and subcommand arguments: {field_names}'
                )

        return positional_args + positional_variadic_arg + subcommand_args + optional_args

    @property
    def root_parser(self) -> T:
        """The connected root parser instance."""
        return self._root_parser

    def _connect_parser_method(
        self, parser_method: Callable[..., Any] | None, method_name: str, *args: Any, **kwargs: Any
    ) -> Callable[..., Any]:
        if (
            parser_method is not None
            and self.case_sensitive is False
            and method_name == 'parse_args_method'
            and isinstance(self._root_parser, _CliInternalArgParser)
        ):

            def parse_args_insensitive_method(
                root_parser: _CliInternalArgParser,
                args: list[str] | tuple[str, ...] | None = None,
                namespace: Namespace | None = None,
            ) -> Any:
                insensitive_args = []
                for arg in shlex.split(shlex.join(args)) if args else []:
                    flag_prefix = rf'\{self.cli_flag_prefix_char}{{1,2}}'
                    matched = re.match(rf'^({flag_prefix}[^\s=]+)(.*)', arg)
                    if matched:
                        arg = matched.group(1).lower() + matched.group(2)
                    insensitive_args.append(arg)
                return parser_method(root_parser, insensitive_args, namespace)  # type: ignore

            return parse_args_insensitive_method

        elif parser_method is None:

            def none_parser_method(*args: Any, **kwargs: Any) -> Any:
                raise SettingsError(
                    f'cannot connect CLI settings source root parser: {method_name} is set to `None` but is needed for connecting'
                )

            return none_parser_method

        else:
            return parser_method

    def _connect_group_method(self, add_argument_group_method: Callable[..., Any] | None) -> Callable[..., Any]:
        add_argument_group = self._connect_parser_method(add_argument_group_method, 'add_argument_group_method')

        def add_group_method(parser: Any, **kwargs: Any) -> Any:
            if not kwargs.pop('_is_cli_mutually_exclusive_group'):
                kwargs.pop('required')
                return add_argument_group(parser, **kwargs)
            else:
                main_group_kwargs = {arg: kwargs.pop(arg) for arg in ['title', 'description'] if arg in kwargs}
                main_group_kwargs['title'] += ' (mutually exclusive)'
                group = add_argument_group(parser, **main_group_kwargs)
                if not hasattr(group, 'add_mutually_exclusive_group'):
                    raise SettingsError(
                        'cannot connect CLI settings source root parser: '
                        'group object is missing add_mutually_exclusive_group but is needed for connecting'
                    )
                return group.add_mutually_exclusive_group(**kwargs)

        return add_group_method

    def _connect_root_parser(
        self,
        root_parser: T,
        parse_args_method: Callable[..., Any] | None,
        add_argument_method: Callable[..., Any] | None = ArgumentParser.add_argument,
        add_argument_group_method: Callable[..., Any] | None = ArgumentParser.add_argument_group,
        add_parser_method: Callable[..., Any] | None = _SubParsersAction.add_parser,
        add_subparsers_method: Callable[..., Any] | None = ArgumentParser.add_subparsers,
        formatter_class: Any = RawDescriptionHelpFormatter,
    ) -> None:
        def _parse_known_args(*args: Any, **kwargs: Any) -> Namespace:
            return ArgumentParser.parse_known_args(*args, **kwargs)[0]

        self._root_parser = root_parser
        if parse_args_method is None:
            parse_args_method = _parse_known_args if self.cli_ignore_unknown_args else ArgumentParser.parse_args
        self._parse_args = self._connect_parser_method(parse_args_method, 'parse_args_method')
        self._add_argument = self._connect_parser_method(add_argument_method, 'add_argument_method')
        self._add_group = self._connect_group_method(add_argument_group_method)
        self._add_parser = self._connect_parser_method(add_parser_method, 'add_parser_method')
        self._add_subparsers = self._connect_parser_method(add_subparsers_method, 'add_subparsers_method')
        self._formatter_class = formatter_class
        self._cli_dict_args: dict[str, type[Any] | None] = {}
        self._cli_subcommands: defaultdict[str, dict[str, str]] = defaultdict(dict)
        self._add_parser_args(
            parser=self.root_parser,
            model=self.settings_cls,
            added_args=[],
            arg_prefix=self.env_prefix,
            subcommand_prefix=self.env_prefix,
            group=None,
            alias_prefixes=[],
            model_default=PydanticUndefined,
        )

    def _add_parser_args(
        self,
        parser: Any,
        model: type[BaseModel],
        added_args: list[str],
        arg_prefix: str,
        subcommand_prefix: str,
        group: Any,
        alias_prefixes: list[str],
        model_default: Any,
        is_model_suppressed: bool = False,
    ) -> ArgumentParser:
        subparsers: Any = None
        alias_path_args: dict[str, str] = {}
        # Ignore model default if the default is a model and not a subclass of the current model.
        model_default = (
            None
            if (
                (is_model_class(type(model_default)) or is_pydantic_dataclass(type(model_default)))
                and not issubclass(type(model_default), model)
            )
            else model_default
        )
        for field_name, field_info in self._sort_arg_fields(model):
            sub_models: list[type[BaseModel]] = self._get_sub_models(model, field_name, field_info)
            alias_names, is_alias_path_only = _get_alias_names(
                field_name, field_info, alias_path_args=alias_path_args, case_sensitive=self.case_sensitive
            )
            preferred_alias = alias_names[0]
            if _CliSubCommand in field_info.metadata:
                for model in sub_models:
                    subcommand_alias = self._check_kebab_name(
                        model.__name__ if len(sub_models) > 1 else preferred_alias
                    )
                    subcommand_name = f'{arg_prefix}{subcommand_alias}'
                    subcommand_dest = f'{arg_prefix}{preferred_alias}'
                    self._cli_subcommands[f'{arg_prefix}:subcommand'][subcommand_name] = subcommand_dest

                    subcommand_help = None if len(sub_models) > 1 else field_info.description
                    if self.cli_use_class_docs_for_groups:
                        subcommand_help = None if model.__doc__ is None else dedent(model.__doc__)

                    subparsers = (
                        self._add_subparsers(
                            parser,
                            title='subcommands',
                            dest=f'{arg_prefix}:subcommand',
                            description=field_info.description if len(sub_models) > 1 else None,
                        )
                        if subparsers is None
                        else subparsers
                    )

                    if hasattr(subparsers, 'metavar'):
                        subparsers.metavar = (
                            f'{subparsers.metavar[:-1]},{subcommand_alias}}}'
                            if subparsers.metavar
                            else f'{{{subcommand_alias}}}'
                        )

                    self._add_parser_args(
                        parser=self._add_parser(
                            subparsers,
                            subcommand_alias,
                            help=subcommand_help,
                            formatter_class=self._formatter_class,
                            description=None if model.__doc__ is None else dedent(model.__doc__),
                        ),
                        model=model,
                        added_args=[],
                        arg_prefix=f'{arg_prefix}{preferred_alias}.',
                        subcommand_prefix=f'{subcommand_prefix}{preferred_alias}.',
                        group=None,
                        alias_prefixes=[],
                        model_default=PydanticUndefined,
                    )
            else:
                flag_prefix: str = self._cli_flag_prefix
                is_append_action = _annotation_contains_types(
                    field_info.annotation, (list, set, dict, Sequence, Mapping), is_strip_annotated=True
                )
                is_parser_submodel = sub_models and not is_append_action
                kwargs: dict[str, Any] = {}
                kwargs['default'] = CLI_SUPPRESS
                kwargs['help'] = self._help_format(field_name, field_info, model_default, is_model_suppressed)
                kwargs['metavar'] = self._metavar_format(field_info.annotation)
                kwargs['required'] = (
                    self.cli_enforce_required and field_info.is_required() and model_default is PydanticUndefined
                )
                kwargs['dest'] = (
                    # Strip prefix if validation alias is set and value is not complex.
                    # Related https://github.com/pydantic/pydantic-settings/pull/25
                    f'{arg_prefix}{preferred_alias}'[self.env_prefix_len :]
                    if arg_prefix and field_info.validation_alias is not None and not is_parser_submodel
                    else f'{arg_prefix}{preferred_alias}'
                )

                arg_names = self._get_arg_names(arg_prefix, subcommand_prefix, alias_prefixes, alias_names, added_args)
                if not arg_names or (kwargs['dest'] in added_args):
                    continue

                if is_append_action:
                    kwargs['action'] = 'append'
                    if _annotation_contains_types(field_info.annotation, (dict, Mapping), is_strip_annotated=True):
                        self._cli_dict_args[kwargs['dest']] = field_info.annotation

                if _CliPositionalArg in field_info.metadata:
                    arg_names, flag_prefix = self._convert_positional_arg(
                        kwargs, field_info, preferred_alias, model_default
                    )

                self._convert_bool_flag(kwargs, field_info, model_default)

                if is_parser_submodel:
                    self._add_parser_submodels(
                        parser,
                        model,
                        sub_models,
                        added_args,
                        arg_prefix,
                        subcommand_prefix,
                        flag_prefix,
                        arg_names,
                        kwargs,
                        field_name,
                        field_info,
                        alias_names,
                        model_default=model_default,
                        is_model_suppressed=is_model_suppressed,
                    )
                elif not is_alias_path_only:
                    if group is not None:
                        if isinstance(group, dict):
                            group = self._add_group(parser, **group)
                        added_args += list(arg_names)
                        self._add_argument(
                            group, *(f'{flag_prefix[: len(name)]}{name}' for name in arg_names), **kwargs
                        )
                    else:
                        added_args += list(arg_names)
                        self._add_argument(
                            parser, *(f'{flag_prefix[: len(name)]}{name}' for name in arg_names), **kwargs
                        )

        self._add_parser_alias_paths(parser, alias_path_args, added_args, arg_prefix, subcommand_prefix, group)
        return parser

    def _check_kebab_name(self, name: str) -> str:
        if self.cli_kebab_case:
            return name.replace('_', '-')
        return name

    def _convert_bool_flag(self, kwargs: dict[str, Any], field_info: FieldInfo, model_default: Any) -> None:
        if kwargs['metavar'] == 'bool':
            if (self.cli_implicit_flags or _CliImplicitFlag in field_info.metadata) and (
                _CliExplicitFlag not in field_info.metadata
            ):
                del kwargs['metavar']
                kwargs['action'] = BooleanOptionalAction

    def _convert_positional_arg(
        self, kwargs: dict[str, Any], field_info: FieldInfo, preferred_alias: str, model_default: Any
    ) -> tuple[list[str], str]:
        flag_prefix = ''
        arg_names = [kwargs['dest']]
        kwargs['default'] = PydanticUndefined
        kwargs['metavar'] = self._check_kebab_name(preferred_alias.upper())

        # Note: CLI positional args are always strictly required at the CLI. Therefore, use field_info.is_required in
        # conjunction with model_default instead of the derived kwargs['required'].
        is_required = field_info.is_required() and model_default is PydanticUndefined
        if kwargs.get('action') == 'append':
            del kwargs['action']
            kwargs['nargs'] = '+' if is_required else '*'
        elif not is_required:
            kwargs['nargs'] = '?'

        del kwargs['dest']
        del kwargs['required']
        return arg_names, flag_prefix

    def _get_arg_names(
        self,
        arg_prefix: str,
        subcommand_prefix: str,
        alias_prefixes: list[str],
        alias_names: tuple[str, ...],
        added_args: list[str],
    ) -> list[str]:
        arg_names: list[str] = []
        for prefix in [arg_prefix] + alias_prefixes:
            for name in alias_names:
                arg_name = self._check_kebab_name(
                    f'{prefix}{name}'
                    if subcommand_prefix == self.env_prefix
                    else f'{prefix.replace(subcommand_prefix, "", 1)}{name}'
                )
                if arg_name not in added_args:
                    arg_names.append(arg_name)
        return arg_names

    def _add_parser_submodels(
        self,
        parser: Any,
        model: type[BaseModel],
        sub_models: list[type[BaseModel]],
        added_args: list[str],
        arg_prefix: str,
        subcommand_prefix: str,
        flag_prefix: str,
        arg_names: list[str],
        kwargs: dict[str, Any],
        field_name: str,
        field_info: FieldInfo,
        alias_names: tuple[str, ...],
        model_default: Any,
        is_model_suppressed: bool,
    ) -> None:
        if issubclass(model, CliMutuallyExclusiveGroup):
            # Argparse has deprecated "calling add_argument_group() or add_mutually_exclusive_group() on a
            # mutually exclusive group" (https://docs.python.org/3/library/argparse.html#mutual-exclusion).
            # Since nested models result in a group add, raise an exception for nested models in a mutually
            # exclusive group.
            raise SettingsError('cannot have nested models in a CliMutuallyExclusiveGroup')

        model_group: Any = None
        model_group_kwargs: dict[str, Any] = {}
        model_group_kwargs['title'] = f'{arg_names[0]} options'
        model_group_kwargs['description'] = field_info.description
        model_group_kwargs['required'] = kwargs['required']
        model_group_kwargs['_is_cli_mutually_exclusive_group'] = any(
            issubclass(model, CliMutuallyExclusiveGroup) for model in sub_models
        )
        if model_group_kwargs['_is_cli_mutually_exclusive_group'] and len(sub_models) > 1:
            raise SettingsError('cannot use union with CliMutuallyExclusiveGroup')
        if self.cli_use_class_docs_for_groups and len(sub_models) == 1:
            model_group_kwargs['description'] = None if sub_models[0].__doc__ is None else dedent(sub_models[0].__doc__)

        if model_default is not PydanticUndefined:
            if is_model_class(type(model_default)) or is_pydantic_dataclass(type(model_default)):
                model_default = getattr(model_default, field_name)
        else:
            if field_info.default is not PydanticUndefined:
                model_default = field_info.default
            elif field_info.default_factory is not None:
                model_default = field_info.default_factory
        if model_default is None:
            desc_header = f'default: {self.cli_parse_none_str} (undefined)'
            if model_group_kwargs['description'] is not None:
                model_group_kwargs['description'] = dedent(f'{desc_header}\n{model_group_kwargs["description"]}')
            else:
                model_group_kwargs['description'] = desc_header

        preferred_alias = alias_names[0]
        is_model_suppressed = self._is_field_suppressed(field_info) or is_model_suppressed
        if not self.cli_avoid_json:
            added_args.append(arg_names[0])
            kwargs['nargs'] = '?'
            kwargs['const'] = '{}'
            kwargs['help'] = kwargs['help'] = CLI_SUPPRESS if is_model_suppressed else f'set {arg_names[0]} from JSON string (default: {{}})'
            model_group = self._add_group(parser, **model_group_kwargs)
            self._add_argument(model_group, *(f'{flag_prefix}{name}' for name in arg_names), **kwargs)
        for model in sub_models:
            self._add_parser_args(
                parser=parser,
                model=model,
                added_args=added_args,
                arg_prefix=f'{arg_prefix}{preferred_alias}.',
                subcommand_prefix=subcommand_prefix,
                group=model_group if model_group else model_group_kwargs,
                alias_prefixes=[f'{arg_prefix}{name}.' for name in alias_names[1:]],
                model_default=model_default,
                is_model_suppressed=is_model_suppressed,
            )

    def _add_parser_alias_paths(
        self,
        parser: Any,
        alias_path_args: dict[str, str],
        added_args: list[str],
        arg_prefix: str,
        subcommand_prefix: str,
        group: Any,
    ) -> None:
        if alias_path_args:
            context = parser
            if group is not None:
                context = self._add_group(parser, **group) if isinstance(group, dict) else group
            is_nested_alias_path = arg_prefix.endswith('.')
            arg_prefix = arg_prefix[:-1] if is_nested_alias_path else arg_prefix
            for name, metavar in alias_path_args.items():
                name = '' if is_nested_alias_path else name
                arg_name = (
                    f'{arg_prefix}{name}'
                    if subcommand_prefix == self.env_prefix
                    else f'{arg_prefix.replace(subcommand_prefix, "", 1)}{name}'
                )
                kwargs: dict[str, Any] = {}
                kwargs['default'] = CLI_SUPPRESS
                kwargs['help'] = 'pydantic alias path'
                kwargs['dest'] = f'{arg_prefix}{name}'
                if metavar == 'dict' or is_nested_alias_path:
                    kwargs['metavar'] = 'dict'
                else:
                    kwargs['action'] = 'append'
                    kwargs['metavar'] = 'list'
                if arg_name not in added_args:
                    added_args.append(arg_name)
                    self._add_argument(context, f'{self._cli_flag_prefix}{arg_name}', **kwargs)

    def _get_modified_args(self, obj: Any) -> tuple[str, ...]:
        if not self.cli_hide_none_type:
            return get_args(obj)
        else:
            return tuple([type_ for type_ in get_args(obj) if type_ is not type(None)])

    def _metavar_format_choices(self, args: list[str], obj_qualname: str | None = None) -> str:
        if 'JSON' in args:
            args = args[: args.index('JSON') + 1] + [arg for arg in args[args.index('JSON') + 1 :] if arg != 'JSON']
        metavar = ','.join(args)
        if obj_qualname:
            return f'{obj_qualname}[{metavar}]'
        else:
            return metavar if len(args) == 1 else f'{{{metavar}}}'

    def _metavar_format_recurse(self, obj: Any) -> str:
        """Pretty metavar representation of a type. Adapts logic from `pydantic._repr.display_as_type`."""
        obj = _strip_annotated(obj)
        if _is_function(obj):
            # If function is locally defined use __name__ instead of __qualname__
            return obj.__name__ if '<locals>' in obj.__qualname__ else obj.__qualname__
        elif obj is ...:
            return '...'
        elif isinstance(obj, Representation):
            return repr(obj)
        elif typing_objects.is_typealiastype(obj):
            return str(obj)

        origin = get_origin(obj)
        if origin is None and not isinstance(obj, (type, typing.ForwardRef, typing_extensions.ForwardRef)):
            obj = obj.__class__

        if is_union_origin(origin):
            return self._metavar_format_choices(list(map(self._metavar_format_recurse, self._get_modified_args(obj))))
        elif typing_objects.is_literal(origin):
            return self._metavar_format_choices(list(map(str, self._get_modified_args(obj))))
        elif _lenient_issubclass(obj, Enum):
            return self._metavar_format_choices([val.name for val in obj])
        elif isinstance(obj, _WithArgsTypes):
            return self._metavar_format_choices(
                list(map(self._metavar_format_recurse, self._get_modified_args(obj))),
                obj_qualname=obj.__qualname__ if hasattr(obj, '__qualname__') else str(obj),
            )
        elif obj is type(None):
            return self.cli_parse_none_str
        elif is_model_class(obj):
            return 'JSON'
        elif isinstance(obj, type):
            return obj.__qualname__
        else:
            return repr(obj).replace('typing.', '').replace('typing_extensions.', '')

    def _metavar_format(self, obj: Any) -> str:
        return self._metavar_format_recurse(obj).replace(', ', ',')

    def _help_format(
        self, field_name: str, field_info: FieldInfo, model_default: Any, is_model_suppressed: bool
    ) -> str:
        _help = field_info.description if field_info.description else ''
        if is_model_suppressed or self._is_field_suppressed(field_info):
            return CLI_SUPPRESS

        if field_info.is_required() and model_default in (PydanticUndefined, None):
            if _CliPositionalArg not in field_info.metadata:
                ifdef = 'ifdef: ' if model_default is None else ''
                _help += f' ({ifdef}required)' if _help else f'({ifdef}required)'
        else:
            default = f'(default: {self.cli_parse_none_str})'
            if is_model_class(type(model_default)) or is_pydantic_dataclass(type(model_default)):
                default = f'(default: {getattr(model_default, field_name)})'
            elif model_default not in (PydanticUndefined, None) and _is_function(model_default):
                default = f'(default factory: {self._metavar_format(model_default)})'
            elif field_info.default not in (PydanticUndefined, None):
                enum_name = _annotation_enum_val_to_name(field_info.annotation, field_info.default)
                default = f'(default: {field_info.default if enum_name is None else enum_name})'
            elif field_info.default_factory is not None:
                default = f'(default factory: {self._metavar_format(field_info.default_factory)})'
            _help += f' {default}' if _help else default
        return _help.replace('%', '%%') if issubclass(type(self._root_parser), ArgumentParser) else _help

    def _is_field_suppressed(self, field_info: FieldInfo) -> bool:
        _help = field_info.description if field_info.description else ''
        return _help == CLI_SUPPRESS or CLI_SUPPRESS in field_info.metadata
