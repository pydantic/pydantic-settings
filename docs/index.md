
## Installation

Installation is as simple as:

```bash
pip install pydantic-settings
```

## Usage

If you create a model that inherits from `BaseSettings`, the model initialiser will attempt to determine
the values of any fields not passed as keyword arguments by reading from the environment. (Default values
will still be used if the matching environment variable is not set.)

This makes it easy to:

* Create a clearly-defined, type-hinted application configuration class
* Automatically read modifications to the configuration from environment variables
* Manually override specific settings in the initialiser where desired (e.g. in unit tests)

For example:

```py
from typing import Any, Callable, Set

from pydantic import (
    AliasChoices,
    AmqpDsn,
    BaseModel,
    Field,
    ImportString,
    PostgresDsn,
    RedisDsn,
)

from pydantic_settings import BaseSettings, SettingsConfigDict


class SubModel(BaseModel):
    foo: str = 'bar'
    apple: int = 1


class Settings(BaseSettings):
    auth_key: str = Field(validation_alias='my_auth_key')  # (1)!

    api_key: str = Field(alias='my_api_key')  # (2)!

    redis_dsn: RedisDsn = Field(
        'redis://user:pass@localhost:6379/1',
        validation_alias=AliasChoices('service_redis_dsn', 'redis_url'),  # (3)!
    )
    pg_dsn: PostgresDsn = 'postgres://user:pass@localhost:5432/foobar'
    amqp_dsn: AmqpDsn = 'amqp://user:pass@localhost:5672/'

    special_function: ImportString[Callable[[Any], Any]] = 'math.cos'  # (4)!

    # to override domains:
    # export my_prefix_domains='["foo.com", "bar.com"]'
    domains: Set[str] = set()

    # to override more_settings:
    # export my_prefix_more_settings='{"foo": "x", "apple": 1}'
    more_settings: SubModel = SubModel()

    model_config = SettingsConfigDict(env_prefix='my_prefix_')  # (5)!


print(Settings().model_dump())
"""
{
    'auth_key': 'xxx',
    'api_key': 'xxx',
    'redis_dsn': Url('redis://user:pass@localhost:6379/1'),
    'pg_dsn': MultiHostUrl('postgres://user:pass@localhost:5432/foobar'),
    'amqp_dsn': Url('amqp://user:pass@localhost:5672/'),
    'special_function': math.cos,
    'domains': set(),
    'more_settings': {'foo': 'bar', 'apple': 1},
}
"""
```

1. The environment variable name is overridden using `validation_alias`. In this case, the environment variable
   `my_auth_key` will be read instead of `auth_key`.

    Check the [`Field` documentation](fields.md) for more information.

2. The environment variable name is overridden using `alias`. In this case, the environment variable
   `my_api_key` will be used for both validation and serialization instead of `api_key`.

   Check the [`Field` documentation](fields.md#field-aliases) for more information.

3. The `AliasChoices` class allows to have multiple environment variable names for a single field.
   The first environment variable that is found will be used.

    Check the [`AliasChoices`](fields.md#aliaspath-and-aliaschoices) for more information.

4. The `ImportString` class allows to import an object from a string.
   In this case, the environment variable `special_function` will be read and the function `math.cos` will be imported.

5. The `env_prefix` config setting allows to set a prefix for all environment variables.

    Check the [Environment variable names documentation](#environment-variable-names) for more information.

## Validation of default values

Unlike pydantic `BaseModel`, default values of `BaseSettings` fields are validated by default.
You can disable this behaviour by setting `validate_default=False` either in `model_config`
or on field level by `Field(validate_default=False)`:

```py
from pydantic import Field

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(validate_default=False)

    # default won't be validated
    foo: int = 'test'


print(Settings())
#> foo='test'


class Settings1(BaseSettings):
    # default won't be validated
    foo: int = Field('test', validate_default=False)


print(Settings1())
#> foo='test'
```

Check the [Validation of default values](validators.md#validation-of-default-values) for more information.

## Environment variable names

By default, the environment variable name is the same as the field name.

You can change the prefix for all environment variables by setting the `env_prefix` config setting,
or via the `_env_prefix` keyword argument on instantiation:

```py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='my_prefix_')

    auth_key: str = 'xxx'  # will be read from `my_prefix_auth_key`
```

!!! note
    The default `env_prefix` is `''` (empty string).

If you want to change the environment variable name for a single field, you can use an alias.

There are two ways to do this:

* Using `Field(alias=...)` (see `api_key` above)
* Using `Field(validation_alias=...)` (see `auth_key` above)

Check the [`Field` aliases documentation](fields.md#field-aliases) for more information about aliases.

`env_prefix` does not apply to fields with alias. It means the environment variable name is the same
as field alias:

```py
from pydantic import Field

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix='my_prefix_')

    foo: str = Field('xxx', alias='FooAlias')  # (1)!
```

1. `env_prefix` will be ignored and the value will be read from `FooAlias` environment variable.

### Case-sensitivity

By default, environment variable names are case-insensitive.

If you want to make environment variable names case-sensitive, you can set the `case_sensitive` config setting:

```py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True)

    redis_host: str = 'localhost'
```

When `case_sensitive` is `True`, the environment variable names must match field names (optionally with a prefix),
so in this example `redis_host` could only be modified via `export redis_host`. If you want to name environment variables
all upper-case, you should name attribute all upper-case too. You can still name environment variables anything
you like through `Field(validation_alias=...)`.

Case-sensitivity can also be set via the `_case_sensitive` keyword argument on instantiation.

In case of nested models, the `case_sensitive` setting will be applied to all nested models.

```py
import os

from pydantic import BaseModel, ValidationError

from pydantic_settings import BaseSettings


class RedisSettings(BaseModel):
    host: str
    port: int


class Settings(BaseSettings, case_sensitive=True):
    redis: RedisSettings


os.environ['redis'] = '{"host": "localhost", "port": 6379}'
print(Settings().model_dump())
#> {'redis': {'host': 'localhost', 'port': 6379}}
os.environ['redis'] = '{"HOST": "localhost", "port": 6379}'  # (1)!
try:
    Settings()
except ValidationError as e:
    print(e)
    """
    1 validation error for Settings
    redis.host
      Field required [type=missing, input_value={'HOST': 'localhost', 'port': 6379}, input_type=dict]
        For further information visit https://errors.pydantic.dev/2/v/missing
    """
```

1. Note that the `host` field is not found because the environment variable name is `HOST` (all upper-case).

!!! note
    On Windows, Python's `os` module always treats environment variables as case-insensitive, so the
    `case_sensitive` config setting will have no effect - settings will always be updated ignoring case.

## Parsing environment variable values

By default environment variables are parsed verbatim, including if the value is empty. You can choose to
ignore empty environment variables by setting the `env_ignore_empty` config setting to `True`. This can be
useful if you would prefer to use the default value for a field rather than an empty value from the
environment.

For most simple field types (such as `int`, `float`, `str`, etc.), the environment variable value is parsed
the same way it would be if passed directly to the initialiser (as a string).

Complex types like `list`, `set`, `dict`, and sub-models are populated from the environment by treating the
environment variable's value as a JSON-encoded string.

Another way to populate nested complex variables is to configure your model with the `env_nested_delimiter`
config setting, then use an environment variable with a name pointing to the nested module fields.
What it does is simply explodes your variable into nested models or dicts.
So if you define a variable `FOO__BAR__BAZ=123` it will convert it into `FOO={'BAR': {'BAZ': 123}}`
If you have multiple variables with the same structure they will be merged.

!!! note
    Sub model has to inherit from `pydantic.BaseModel`, Otherwise `pydantic-settings` will initialize sub model,
    collects values for sub model fields separately, and you may get unexpected results.

As an example, given the following environment variables:
```bash
# your environment
export V0=0
export SUB_MODEL='{"v1": "json-1", "v2": "json-2"}'
export SUB_MODEL__V2=nested-2
export SUB_MODEL__V3=3
export SUB_MODEL__DEEP__V4=v4
```

You could load them into the following settings model:

```py
from pydantic import BaseModel

from pydantic_settings import BaseSettings, SettingsConfigDict


class DeepSubModel(BaseModel):  # (1)!
    v4: str


class SubModel(BaseModel):  # (2)!
    v1: str
    v2: bytes
    v3: int
    deep: DeepSubModel


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter='__')

    v0: str
    sub_model: SubModel


print(Settings().model_dump())
"""
{
    'v0': '0',
    'sub_model': {'v1': 'json-1', 'v2': b'nested-2', 'v3': 3, 'deep': {'v4': 'v4'}},
}
"""
```

1. Sub model has to inherit from `pydantic.BaseModel`.

2. Sub model has to inherit from `pydantic.BaseModel`.

`env_nested_delimiter` can be configured via the `model_config` as shown above, or via the
`_env_nested_delimiter` keyword argument on instantiation.

Nested environment variables take precedence over the top-level environment variable JSON
(e.g. in the example above, `SUB_MODEL__V2` trumps `SUB_MODEL`).

You may also populate a complex type by providing your own source class.

```py
import json
import os
from typing import Any, List, Tuple, Type

from pydantic.fields import FieldInfo

from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
)


class MyCustomSource(EnvSettingsSource):
    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        if field_name == 'numbers':
            return [int(x) for x in value.split(',')]
        return json.loads(value)


class Settings(BaseSettings):
    numbers: List[int]

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (MyCustomSource(settings_cls),)


os.environ['numbers'] = '1,2,3'
print(Settings().model_dump())
#> {'numbers': [1, 2, 3]}
```

## Dotenv (.env) support

Dotenv files (generally named `.env`) are a common pattern that make it easy to use environment variables in a
platform-independent manner.

A dotenv file follows the same general principles of all environment variables, and it looks like this:

```bash title=".env"
# ignore comment
ENVIRONMENT="production"
REDIS_ADDRESS=localhost:6379
MEANING_OF_LIFE=42
MY_VAR='Hello world'
```

Once you have your `.env` file filled with variables, *pydantic* supports loading it in two ways:

1. Setting the `env_file` (and `env_file_encoding` if you don't want the default encoding of your OS) on `model_config`
in the `BaseSettings` class:
   ````py hl_lines="4 5"
   from pydantic_settings import BaseSettings, SettingsConfigDict


   class Settings(BaseSettings):
       model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')
   ````
2. Instantiating the `BaseSettings` derived class with the `_env_file` keyword argument
(and the `_env_file_encoding` if needed):
   ````py hl_lines="8"
   from pydantic_settings import BaseSettings, SettingsConfigDict


   class Settings(BaseSettings):
       model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')


   settings = Settings(_env_file='prod.env', _env_file_encoding='utf-8')
   ````
In either case, the value of the passed argument can be any valid path or filename, either absolute or relative to the
current working directory. From there, *pydantic* will handle everything for you by loading in your variables and
validating them.

!!! note
    If a filename is specified for `env_file`, Pydantic will only check the current working directory and
    won't check any parent directories for the `.env` file.

Even when using a dotenv file, *pydantic* will still read environment variables as well as the dotenv file,
**environment variables will always take priority over values loaded from a dotenv file**.

Passing a file path via the `_env_file` keyword argument on instantiation (method 2) will override
the value (if any) set on the `model_config` class. If the above snippets were used in conjunction, `prod.env` would be loaded
while `.env` would be ignored.

If you need to load multiple dotenv files, you can pass multiple file paths as a tuple or list. The files will be
loaded in order, with each file overriding the previous one.

```py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # `.env.prod` takes priority over `.env`
        env_file=('.env', '.env.prod')
    )
```

You can also use the keyword argument override to tell Pydantic not to load any file at all (even if one is set in
the `model_config` class) by passing `None` as the instantiation keyword argument, e.g. `settings = Settings(_env_file=None)`.

Because python-dotenv is used to parse the file, bash-like semantics such as `export` can be used which
(depending on your OS and environment) may allow your dotenv file to also be used with `source`,
see [python-dotenv's documentation](https://saurabh-kumar.com/python-dotenv/#usages) for more details.

Pydantic settings consider `extra` config in case of dotenv file. It means if you set the `extra=forbid` (*default*)
on `model_config` and your dotenv file contains an entry for a field that is not defined in settings model,
it will raise `ValidationError` in settings construction.

For compatibility with pydantic 1.x BaseSettings you should use `extra=ignore`:
```py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
```


!!! note
    Pydantic settings loads all the values from dotenv file and passes it to the model, regardless of the model's `env_prefix`.
    So if you provide extra values in a dotenv file, whether they start with `env_prefix` or not,
    a `ValidationError` will be raised.

## Secrets

Placing secret values in files is a common pattern to provide sensitive configuration to an application.

A secret file follows the same principal as a dotenv file except it only contains a single value and the file name
is used as the key. A secret file will look like the following:

``` title="/var/run/database_password"
super_secret_database_password
```

Once you have your secret files, *pydantic* supports loading it in two ways:

1. Setting the `secrets_dir` on `model_config` in a `BaseSettings` class to the directory where your secret files are stored.
   ````py hl_lines="4 5 6 7"
   from pydantic_settings import BaseSettings, SettingsConfigDict


   class Settings(BaseSettings):
       model_config = SettingsConfigDict(secrets_dir='/var/run')

       database_password: str
   ````
2. Instantiating the `BaseSettings` derived class with the `_secrets_dir` keyword argument:
   ````
   settings = Settings(_secrets_dir='/var/run')
   ````

In either case, the value of the passed argument can be any valid directory, either absolute or relative to the
current working directory. **Note that a non existent directory will only generate a warning**.
From there, *pydantic* will handle everything for you by loading in your variables and validating them.

Even when using a secrets directory, *pydantic* will still read environment variables from a dotenv file or the environment,
**a dotenv file and environment variables will always take priority over values loaded from the secrets directory**.

Passing a file path via the `_secrets_dir` keyword argument on instantiation (method 2) will override
the value (if any) set on the `model_config` class.

### Use Case: Docker Secrets

Docker Secrets can be used to provide sensitive configuration to an application running in a Docker container.
To use these secrets in a *pydantic* application the process is simple. More information regarding creating, managing
and using secrets in Docker see the official
[Docker documentation](https://docs.docker.com/engine/reference/commandline/secret/).

First, define your `Settings` class with a `SettingsConfigDict` that specifies the secrets directory.

```py hl_lines="4 5 6 7"
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(secrets_dir='/run/secrets')

    my_secret_data: str
```

!!! note
    By default [Docker uses `/run/secrets`](https://docs.docker.com/engine/swarm/secrets/#how-docker-manages-secrets)
    as the target mount point. If you want to use a different location, change `Config.secrets_dir` accordingly.

Then, create your secret via the Docker CLI
```bash
printf "This is a secret" | docker secret create my_secret_data -
```

Last, run your application inside a Docker container and supply your newly created secret
```bash
docker service create --name pydantic-with-secrets --secret my_secret_data pydantic-app:latest
```

## Other settings source

Other settings sources are available for common configuration files:

- `TomlConfigSettingsSource` using `toml_file` and toml_file_encoding arguments
- `YamlConfigSettingsSource` using `yaml_file` and yaml_file_encoding arguments
- `JsonConfigSettingsSource` using `json_file` and `json_file_encoding` arguments

You can also provide multiple files by providing a list of path:
```py
toml_file = ['config.default.toml', 'config.custom.toml']
```
To use them, you can use the same mechanism described [here](#customise-settings-sources)


```py
from typing import Tuple, Type

from pydantic import BaseModel

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)


class Nested(BaseModel):
    nested_field: str


class Settings(BaseSettings):
    foobar: str
    nested: Nested
    model_config = SettingsConfigDict(
        toml_file='config.toml', toml_file_encoding='utf-8'
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (TomlConfigSettingsSource(settings_cls),)
```

This will be able to read the following "config.toml" file, located in your working directory:

```toml
foobar = "Hello"
[nested]
nested_field = "world!"
```

## Field value priority

In the case where a value is specified for the same `Settings` field in multiple ways,
the selected value is determined as follows (in descending order of priority):

1. Arguments passed to the `Settings` class initialiser.
2. Environment variables, e.g. `my_prefix_special_function` as described above.
3. Variables loaded from a dotenv (`.env`) file.
4. Variables loaded from the secrets directory.
5. The default field values for the `Settings` model.

## Customise settings sources

If the default order of priority doesn't match your needs, it's possible to change it by overriding
the `settings_customise_sources` method of your `Settings` .

`settings_customise_sources` takes four callables as arguments and returns any number of callables as a tuple.
In turn these callables are called to build the inputs to the fields of the settings class.

Each callable should take an instance of the settings class as its sole argument and return a `dict`.

### Changing Priority

The order of the returned callables decides the priority of inputs; first item is the highest priority.

```py
from typing import Tuple, Type

from pydantic import PostgresDsn

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource


class Settings(BaseSettings):
    database_dsn: PostgresDsn

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return env_settings, init_settings, file_secret_settings


print(Settings(database_dsn='postgres://postgres@localhost:5432/kwargs_db'))
#> database_dsn=MultiHostUrl('postgres://postgres@localhost:5432/kwargs_db')
```

By flipping `env_settings` and `init_settings`, environment variables now have precedence over `__init__` kwargs.

### Adding sources

As explained earlier, *pydantic* ships with multiples built-in settings sources. However, you may occasionally
need to add your own custom sources, `settings_customise_sources` makes this very easy:

```py
import json
from pathlib import Path
from typing import Any, Dict, Tuple, Type

from pydantic.fields import FieldInfo

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class JsonConfigSettingsSource(PydanticBaseSettingsSource):
    """
    A simple settings source class that loads variables from a JSON file
    at the project's root.

    Here we happen to choose to use the `env_file_encoding` from Config
    when reading `config.json`
    """

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> Tuple[Any, str, bool]:
        encoding = self.config.get('env_file_encoding')
        file_content_json = json.loads(
            Path('tests/example_test_config.json').read_text(encoding)
        )
        field_value = file_content_json.get(field_name)
        return field_value, field_name, False

    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        return value

    def __call__(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}

        for field_name, field in self.settings_cls.model_fields.items():
            field_value, field_key, value_is_complex = self.get_field_value(
                field, field_name
            )
            field_value = self.prepare_field_value(
                field_name, field, field_value, value_is_complex
            )
            if field_value is not None:
                d[field_key] = field_value

        return d


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file_encoding='utf-8')

    foobar: str

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            JsonConfigSettingsSource(settings_cls),
            env_settings,
            file_secret_settings,
        )


print(Settings())
#> foobar='test'
```

### Removing sources

You might also want to disable a source:

```py
from typing import Tuple, Type

from pydantic import ValidationError

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource


class Settings(BaseSettings):
    my_api_key: str

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        # here we choose to ignore arguments from init_settings
        return env_settings, file_secret_settings


try:
    Settings(my_api_key='this is ignored')
except ValidationError as exc_info:
    print(exc_info)
    """
    1 validation error for Settings
    my_api_key
      Field required [type=missing, input_value={}, input_type=dict]
        For further information visit https://errors.pydantic.dev/2/v/missing
    """
```
