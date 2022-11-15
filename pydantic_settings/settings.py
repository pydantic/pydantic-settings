import inspect
import warnings
from typing import AbstractSet, Any, Callable, ClassVar, Dict, Iterator, List, Mapping, Optional, Tuple, Type, Union

from pydantic.config import BaseConfig, Extra
from pydantic.fields import ModelField
from pydantic.main import BaseModel
from pydantic.typing import StrPath, display_as_type
from pydantic.utils import deep_update, sequence_like

from .source_mappers import SourceMapper
from .source_providers import env_source_provider, secret_source_provider
from .utils import DotenvType, SettingsError, env_file_sentinel

SettingsSourceCallable = Callable[[Iterator[ModelField]], Dict[str, Any]]


class BaseSettings(BaseModel):
    """
    Base class for settings, allowing values to be overridden by environment variables.

    This is useful in production for secrets you do not wish to save in code, it plays nicely with docker(-compose),
    Heroku and any 12 factor app design.
    """

    def __init__(
        __pydantic_self__,
        _env_file: Optional[DotenvType] = env_file_sentinel,
        _env_file_encoding: Optional[str] = None,
        _env_nested_delimiter: Optional[str] = None,
        _secrets_dir: Optional[StrPath] = None,
        **values: Any,
    ) -> None:
        # Uses something other than `self` the first arg to allow "self" as a settable attribute
        super().__init__(
            **__pydantic_self__._build_values(
                values,
                _env_file=_env_file,
                _env_file_encoding=_env_file_encoding,
                _env_nested_delimiter=_env_nested_delimiter,
                _secrets_dir=_secrets_dir,
            )
        )

    def _build_values(
        self,
        init_kwargs: Dict[str, Any],
        _env_file: Optional[DotenvType] = None,
        _env_file_encoding: Optional[str] = None,
        _env_nested_delimiter: Optional[str] = None,
        _secrets_dir: Optional[StrPath] = None,
    ) -> Dict[str, Any]:
        def get_attribute(name: str) -> Any:
            attr_with_fallback: Dict[str, Tuple[Any, str]] = {
                'env_file_paths': (
                    _env_file if _env_file != env_file_sentinel else self.__config__.env_file,
                    '_env_file and Config.env_file is depricated in favor of Config.env_file_paths',
                ),
                'env_file_encoding': (
                    _env_file_encoding if _env_file_encoding else self.__config__.env_file_encoding,
                    '_env_file_encoding, is depricated in favor of Config.env_file_encoding',
                ),
                'nesting_delimiter': (
                    _env_nested_delimiter
                    if _env_nested_delimiter is not None
                    else self.__config__.env_nested_delimiter,
                    '_env_nested_delimiter, Config.env_nested_delimiter depricated \
                        in favor of Config.nesting_delimiter',
                ),
                'prefix': (self.__config__.env_prefix, 'Config.env_prifix depricated in favor of Config.prefix'),
                'secrets_dir_path': (
                    _secrets_dir if _secrets_dir else self.__config__.secrets_dir,
                    '_secrets_dir, Config.secrets_dir depricated in favor of secrets_dir_path',
                ),
            }
            value = getattr(self.__config__, name, None)
            if not value and name in attr_with_fallback:
                value, warning = attr_with_fallback.get(name, (None, None))
                if warning:
                    warnings.warn(warning, DeprecationWarning)
            return value

        # init_kwargs are treated separately from all other sources. The
        # Config.sources need not include the init_kwargs. If the user wishes to
        # override the init_kwargs, they can do so with customize_sources
        _mappers: List[SettingsSourceCallable] = [
            lambda settings: init_kwargs,
        ]
        for source_provider in self.__config__.source_providers:
            # The following subroutine instantiates the source provider. For the
            # instantiation, it will search for instantiation attributes from
            # Config class. Config class must contain attribute with exact name
            # as the parameter expected by the provider function. The reason we
            # are taking instantiation here is that use don't have to themselves
            # instantiate during the compile time rather we take it during the
            # runtime and is helpful specially in the case of instances where
            # user needs to login etc.
            signature = inspect.signature(source_provider)
            kwargs = {}
            args = []
            for parameter in signature.parameters.values():
                parameter_value = get_attribute(parameter.name)
                if not parameter_value and parameter.default != inspect._empty:
                    parameter_value = parameter.default
                if parameter.kind in {parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY}:
                    kwargs[parameter.name] = parameter_value
                elif parameter.kind in {parameter.VAR_KEYWORD, parameter.VAR_POSITIONAL}:
                    raise SettingsError("`*args`, `**kwargs` isn't supported for the sources yet.")
                else:
                    args.append(parameter_value)
            source = source_provider(*args, **kwargs)
            _mappers.append(
                SourceMapper(
                    source=source,
                    case_sensitive=self.__config__.case_sensitive,
                    nesting_delimiter=get_attribute('nesting_delimiter'),
                    complex_parser=self.__config__.parse_env_var,
                    get_field_info=self.__config__.get_field_info,
                ),
            )
        mappers = self.__config__.customise_sources(*_mappers)
        if mappers:
            return deep_update(*reversed([source(iter(self.__fields__.values())) for source in mappers]))
        else:
            # no one should mean to do this, but I think returning an empty dict is marginally preferable
            # to an informative error and much better than a confusing error
            return {}

    class Config(BaseConfig):
        env_prefix: str = ''
        env_file: Optional[DotenvType] = None
        env_file_encoding: Optional[str] = None
        env_nested_delimiter: Optional[str] = None
        secrets_dir: Optional[StrPath] = None
        validate_all: bool = True
        extra: Extra = Extra.forbid
        arbitrary_types_allowed: bool = True
        case_sensitive: bool = False
        # TODO: Make source configurable from here, like setting Mapper Class, kwargs for Mapper class etc.
        source_providers: List[Callable[..., Mapping[str, Any]]] = [env_source_provider, secret_source_provider]

        @classmethod
        def prepare_field(cls, field: ModelField) -> None:
            env_names: Union[List[str], AbstractSet[str]]
            field_info_from_config = cls.get_field_info(field.name)

            env = field_info_from_config.get('env') or field.field_info.extra.get('env')
            if env is None:
                if field.has_alias:
                    warnings.warn(
                        'aliases are no longer used by BaseSettings to define which environment variables to read. '
                        'Instead use the "env" field setting. '
                        'See https://pydantic-docs.helpmanual.io/usage/settings/#environment-variable-names',
                        FutureWarning,
                    )
                env_names = {cls.env_prefix + field.name}
            elif isinstance(env, str):
                env_names = {env}
            elif isinstance(env, (set, frozenset)):
                env_names = env
            elif sequence_like(env):
                env_names = list(env)
            else:
                raise TypeError(f'invalid field env: {env!r} ({display_as_type(env)}); should be string, list or set')

            if not cls.case_sensitive:
                env_names = env_names.__class__(n.lower() for n in env_names)
            field.field_info.extra['env_names'] = env_names

        @classmethod
        def customise_sources(
            cls,
            init_settings: SettingsSourceCallable,
            env_settings: SettingsSourceCallable,
            file_secret_settings: SettingsSourceCallable,
        ) -> Tuple[SettingsSourceCallable, ...]:
            return init_settings, env_settings, file_secret_settings

        @classmethod
        def parse_env_var(cls, field_name: str, raw_val: str) -> Any:
            return cls.json_loads(raw_val)

    # populated by the metaclass using the Config class defined above, annotated here to help IDEs only
    __config__: ClassVar[Type[Config]]
