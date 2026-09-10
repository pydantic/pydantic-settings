# Inheriting dotenv files

By default, a subclass's `env_file` replaces the value inherited from its parents.
Set `env_file_inherit=True` to keep parent dotenv files as fallbacks instead. This
is useful when a project has shared settings and each service or submodule has
its own overrides.

```python
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

Path('common.env').write_text(
    'MYAPP_HOST=localhost\nMYAPP_PORT=8000\n', encoding='utf-8'
)
Path('service.env').write_text('MYAPP_PORT=9000\n', encoding='utf-8')
Path('runtime.env').write_text('MYAPP_PORT=9100\n', encoding='utf-8')


class CommonSettings(BaseSettings):
    host: str
    port: int

    model_config = SettingsConfigDict(env_file='common.env', env_prefix='MYAPP_')


class ServiceSettings(CommonSettings):
    model_config = SettingsConfigDict(env_file='service.env', env_file_inherit=True)


assert ServiceSettings().model_dump() == {'host': 'localhost', 'port': 9000}
assert ServiceSettings(_env_file='runtime.env').model_dump() == {
    'host': 'localhost',
    'port': 9100,
}
assert ServiceSettings(_env_file=None, host='manual', port=1234).model_dump() == {
    'host': 'manual',
    'port': 1234,
}
```

## File order and overrides

Within the existing dotenv source, files are collected from each class's
effective `model_config` in reverse Python method resolution order. The final
class's effective `env_file` takes precedence over the other bases' files. This
includes an `env_file` inherited through Pydantic's multiple-base configuration
merging. Explicit `_env_file` paths are then added as the highest-priority files.

A single path, a list, or a tuple is accepted at each level. As with ordinary
multi-file dotenv loading, later files override earlier occurrences of the same
environment-variable name. Repeated paths are loaded only once, at their
highest-priority position. Strings and equivalent `Path` objects are treated as
the same path; symbolic links are not resolved for deduplication.

This only changes which files the dotenv source reads. Field aliases, nested
values, JSON decoding, extra-field validation, and custom source ordering keep
their existing behavior. In particular, environment variables and constructor
values retain their normal priority over dotenv values, and dotenv values still
take priority over secret files. Files are not parsed as separate settings models.

## Enabling or disabling inheritance

`env_file_inherit` defaults to `False`. Set it in `SettingsConfigDict`, as a class
keyword, or override it for one instance with `_env_file_inherit=True` or
`_env_file_inherit=False`. Custom sources can use
`DotEnvSettingsSource(Settings, env_file_inherit=True)` directly.

With inheritance enabled, explicit `_env_file` paths supplement the configured
files rather than replace them. Set the final model's `env_file`, or the instance's
`_env_file`, to `None`, an empty string, or an empty sequence to disable **all**
dotenv loading. An empty `env_file` on an ancestor contributes no files; it does
not hide files configured by other ancestors when the final model enables loading.

`_env_file_inherit=False` disables only the inherited fallbacks and restores the
usual file-replacement behavior. It does not disable the final model's own file.
For `CliApp.run`, configure inheritance on the settings model; for a direct
settings constructor using `_cli_parse_args`, the per-instance override also works.

All files use the final settings model's encoding, case-sensitivity, parsing,
filtering, and `env_file_depth` options. Relative paths are interpreted from the
working directory, not from the module defining each class. Missing files are
ignored according to the normal dotenv rules. The option does not introduce
cross-file variable interpolation or deep merging of JSON strings.
