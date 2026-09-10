from pathlib import Path
from unittest import mock

import pytest
from pydantic import BaseModel, Field, ValidationError

from pydantic_settings import BaseSettings, CliApp, DotEnvSettingsSource, SettingsConfigDict


@pytest.fixture
def dotenv_family(tmp_path):
    parent_file = tmp_path / 'parent.env'
    child_file = tmp_path / 'child.env'
    runtime_file = tmp_path / 'runtime.env'
    parent_file.write_text('PARENT_VALUE=1\nSHARED=parent\n')
    child_file.write_text('CHILD_VALUE=2\nSHARED=child\n')
    runtime_file.write_text('RUNTIME_VALUE=3\nSHARED=runtime\n')

    class Parent(BaseSettings):
        parent_value: int = 0
        child_value: int = 0
        runtime_value: int = 0
        shared: str = 'default'

        model_config = SettingsConfigDict(env_file=parent_file)

    class Child(Parent):
        model_config = SettingsConfigDict(env_file=child_file)

    return Parent, Child, parent_file, child_file, runtime_file


def test_env_file_inherit_parent_fallback(dotenv_family):
    Parent, Child, *_ = dotenv_family

    class Inherited(Child):
        model_config = SettingsConfigDict(env_file_inherit=True)

    assert Inherited().model_dump() == {
        'parent_value': 1,
        'child_value': 2,
        'runtime_value': 0,
        'shared': 'child',
    }
    assert Parent().shared == 'parent'
    assert Child().parent_value == 0


def test_env_file_inherit_class_keyword(dotenv_family):
    _, Child, *_ = dotenv_family

    class Inherited(Child, env_file_inherit=True):
        pass

    assert Inherited().parent_value == 1
    assert Inherited.model_config['env_file_inherit'] is True
    assert 'env_file_inherit' not in Inherited.model_fields


def test_env_file_inherit_instance_and_source_overrides(dotenv_family):
    _, Child, *_ = dotenv_family

    class Inherited(Child):
        model_config = SettingsConfigDict(env_file_inherit=True)

    assert Child(_env_file_inherit=True).parent_value == 1
    assert Inherited(_env_file_inherit=False).parent_value == 0
    assert DotEnvSettingsSource(Child, env_file_inherit=True)()['parent_value'] == '1'
    assert 'parent_value' not in DotEnvSettingsSource(Inherited, env_file_inherit=False)()


@pytest.mark.parametrize('path_type', [str, Path, list, tuple])
def test_env_file_inherit_runtime_override(dotenv_family, path_type):
    _, Child, _, _, runtime_file = dotenv_family
    env_file = path_type([runtime_file]) if path_type in (list, tuple) else path_type(runtime_file)

    settings = Child(_env_file=env_file, _env_file_inherit=True)
    assert settings.model_dump() == {
        'parent_value': 1,
        'child_value': 2,
        'runtime_value': 3,
        'shared': 'runtime',
    }
    # Without the opt-in, an explicit file still replaces the configured file(s).
    assert Child(_env_file=env_file).model_dump() == {
        'parent_value': 0,
        'child_value': 0,
        'runtime_value': 3,
        'shared': 'runtime',
    }


@pytest.mark.parametrize('env_file', [None, '', [], ()])
@pytest.mark.parametrize('override', ['instance', 'config', 'source'])
def test_env_file_inherit_disable_all_dotenv(dotenv_family, env_file, override):
    _, Child, *_ = dotenv_family

    class Inherited(Child):
        model_config = SettingsConfigDict(env_file_inherit=True)

    with mock.patch.object(DotEnvSettingsSource, '_read_env_file', side_effect=AssertionError('unexpected file read')):
        if override == 'instance':
            settings = Inherited(_env_file=env_file)
        elif override == 'config':

            class Disabled(Inherited):
                model_config = SettingsConfigDict(env_file=env_file)

            settings = Disabled()
        else:
            assert DotEnvSettingsSource(Inherited, env_file=env_file)() == {}
            return
    assert settings.shared == 'default'
    assert settings.parent_value == settings.child_value == 0


def test_env_file_inherit_lists_duplicates_and_no_mutation(dotenv_family):
    Parent, _, parent_file, child_file, runtime_file = dotenv_family
    parent_files = [parent_file, str(child_file)]
    child_files = (child_file, runtime_file, str(child_file))

    class MultipleParent(Parent):
        model_config = SettingsConfigDict(env_file=parent_files)

    class MultipleChild(MultipleParent):
        model_config = SettingsConfigDict(env_file=child_files, env_file_inherit=True)

    read_file = DotEnvSettingsSource._read_env_file
    with mock.patch.object(DotEnvSettingsSource, '_read_env_file', autospec=True, side_effect=read_file) as read:
        source = DotEnvSettingsSource(MultipleChild)
    assert [call.args[1] for call in read.call_args_list] == [parent_file, runtime_file, child_file]
    assert source.env_file == (parent_file, runtime_file, child_file)
    assert source()['shared'] == 'child'
    assert parent_files == [parent_file, str(child_file)]
    assert child_files == (child_file, runtime_file, str(child_file))
    assert MultipleParent.model_config['env_file'] is parent_files
    assert MultipleChild.model_config['env_file'] is child_files


@pytest.mark.parametrize('missing', ['parent', 'child'])
def test_env_file_inherit_missing_files(dotenv_family, missing):
    _, Child, parent_file, child_file, _ = dotenv_family
    (parent_file if missing == 'parent' else child_file).unlink()
    settings = Child(_env_file_inherit=True)
    assert settings.shared == ('child' if missing == 'parent' else 'parent')
    assert settings.parent_value == (0 if missing == 'parent' else 1)
    assert settings.child_value == (2 if missing == 'parent' else 0)


@pytest.mark.parametrize('explicit_child_file', [False, True])
def test_env_file_inherit_diamond_and_effective_config(tmp_path, explicit_child_file):
    paths = {name: tmp_path / f'{name}.env' for name in ('root', 'left', 'right', 'child')}
    for name, path in paths.items():
        path.write_text(f'SHARED={name}\n{name.upper()}_VALUE=1\n')

    class Root(BaseSettings):
        shared: str
        root_value: int = 0
        left_value: int = 0
        right_value: int = 0
        child_value: int = 0

        model_config = SettingsConfigDict(env_file=paths['root'], env_file_inherit=True)

    class Left(Root):
        model_config = SettingsConfigDict(env_file=paths['left'])

    class Right(Root):
        model_config = SettingsConfigDict(env_file=paths['right'])

    class Diamond(Left, Right):
        model_config = SettingsConfigDict(env_file=paths['child']) if explicit_child_file else SettingsConfigDict()

    settings = Diamond()
    assert settings.root_value == settings.left_value == settings.right_value == 1
    assert settings.child_value == int(explicit_child_file)
    assert settings.shared == ('child' if explicit_child_file else 'right')
    # Pydantic's effective config wins, even when inherited from the rightmost base.
    expected = ('root', 'right', 'left', 'child') if explicit_child_file else ('root', 'left', 'right')
    assert DotEnvSettingsSource(Diamond).env_file == tuple(paths[name] for name in expected)


def test_env_file_inherit_siblings_and_fresh_reads(dotenv_family, tmp_path):
    Parent, Child, parent_file, *_ = dotenv_family
    sibling_file = tmp_path / 'sibling.env'
    sibling_file.write_text('SHARED=sibling\n')

    class Sibling(Parent):
        model_config = SettingsConfigDict(env_file=sibling_file, env_file_inherit=True)

    assert Child(_env_file_inherit=True).child_value == 2
    assert Sibling().child_value == 0
    assert Sibling().shared == 'sibling'
    parent_file.write_text('PARENT_VALUE=4\nSHARED=changed-parent\n')
    assert Sibling().parent_value == Child(_env_file_inherit=True).parent_value == 4
    assert Parent().shared == 'changed-parent'


def test_env_file_inherit_nested_aliases_and_filtering(tmp_path):
    parent_file = tmp_path / 'parent.env'
    child_file = tmp_path / 'child.env'
    parent_file.write_text('APP_DATABASE__HOST=localhost\nAPP_ITEMS=[1,2]\nUNRELATED=ignore\n')
    child_file.write_text('APP_DATABASE__PORT=5433\nAUTH_TOKEN=child-token\n')

    class Database(BaseModel):
        host: str
        port: int

    class Parent(BaseSettings):
        database: Database
        items: list[int]
        token: str = Field(validation_alias='AUTH_TOKEN')

        model_config = SettingsConfigDict(
            env_file=parent_file, env_prefix='APP_', env_nested_delimiter='__', dotenv_filtering='only_existing'
        )

    class Child(Parent):
        model_config = SettingsConfigDict(env_file=child_file, env_file_inherit=True)

    assert Child().model_dump() == {
        'database': {'host': 'localhost', 'port': 5433},
        'items': [1, 2],
        'token': 'child-token',
    }


def test_env_file_inherit_depth_encoding_and_empty_values(tmp_path, monkeypatch):
    (tmp_path / 'parent.env').write_text('NAME=caf\xe9\nSHARED=parent\n', encoding='latin-1')
    child_dir = tmp_path / 'child'
    child_dir.mkdir()
    (child_dir / 'child.env').write_text('SHARED=\n', encoding='latin-1')
    monkeypatch.chdir(child_dir)

    class Parent(BaseSettings):
        name: str
        shared: str

        model_config = SettingsConfigDict(env_file='parent.env', env_file_encoding='latin-1', env_file_depth=1)

    class Child(Parent):
        model_config = SettingsConfigDict(env_file='child.env', env_file_inherit=True, env_ignore_empty=True)

    assert Child().model_dump() == {'name': 'caf\xe9', 'shared': 'parent'}
    assert Child(_env_ignore_empty=False).shared == ''


def test_env_file_inherit_source_precedence_and_cli(dotenv_family, env):
    _, Child, *_ = dotenv_family
    env.set('SHARED', 'environment')
    assert Child(_env_file_inherit=True).shared == 'environment'
    assert Child(_env_file_inherit=True, shared='constructor').shared == 'constructor'
    settings = Child(_cli_parse_args=['--shared', 'command-line'], _env_file_inherit=True)
    assert settings.shared == 'command-line'
    assert settings.parent_value == 1

    class App(Child, env_file_inherit=True):
        pass

    app = CliApp.run(App, cli_args=['--shared', 'app-command-line'])
    assert app.shared == 'app-command-line'
    assert app.parent_value == 1


def test_env_file_inherit_custom_source_order(dotenv_family, env):
    _, Child, *_ = dotenv_family

    class Custom(Child):
        model_config = SettingsConfigDict(env_file_inherit=True)

        @classmethod
        def settings_customise_sources(
            cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
        ):
            return dotenv_settings, env_settings, init_settings, file_secret_settings

    env.set('SHARED', 'environment')
    settings = Custom(shared='constructor')
    assert settings.shared == 'child'
    assert settings.parent_value == 1


def test_env_file_inherit_preserves_extra_validation(dotenv_family):
    _, Child, parent_file, *_ = dotenv_family
    parent_file.write_text('UNDECLARED=value\n')
    with pytest.raises(ValidationError) as exc_info:
        Child(_env_file_inherit=True)
    assert exc_info.value.errors(include_url=False) == [
        {'type': 'extra_forbidden', 'loc': ('undeclared',), 'msg': 'Extra inputs are not permitted', 'input': 'value'}
    ]


def test_env_file_inherit_keeps_secrets_below_dotenv(dotenv_family, tmp_path):
    _, Child, *_ = dotenv_family
    secrets_dir = tmp_path / 'secrets'
    secrets_dir.mkdir()
    for name, value in {'PARENT_VALUE': '9', 'RUNTIME_VALUE': '7', 'SHARED': 'secret'}.items():
        (secrets_dir / name).write_text(value)

    class WithSecrets(Child):
        model_config = SettingsConfigDict(env_file_inherit=True, secrets_dir=secrets_dir)

    assert WithSecrets().model_dump() == {
        'parent_value': 1,
        'child_value': 2,
        'runtime_value': 7,
        'shared': 'child',
    }


def test_env_file_inherit_case_sensitivity_and_none_parsing(dotenv_family):
    _, Child, parent_file, child_file, _ = dotenv_family
    parent_file.write_text('parent_value=1\nshared=null\n')
    child_file.write_text('child_value=2\n')

    class Sensitive(Child):
        shared: str | None = None

        model_config = SettingsConfigDict(env_file_inherit=True, case_sensitive=True, env_parse_none_str='null')

    settings = Sensitive()
    assert settings.parent_value == 1
    assert settings.child_value == 2
    assert settings.shared is None


def test_env_file_inherit_preinitialized_sources(dotenv_family):
    _, Child, *_ = dotenv_family
    sources = Child._settings_init_sources(_env_file_inherit=True)
    assert Child(_build_sources=sources).parent_value == 1


def test_env_file_inherit_runtime_file_without_configured_files(dotenv_family):
    *_, runtime_file = dotenv_family

    class Settings(BaseSettings):
        runtime_value: int
        shared: str

    assert Settings(_env_file=runtime_file, _env_file_inherit=True).model_dump() == {
        'runtime_value': 3,
        'shared': 'runtime',
    }


def test_env_file_inherit_empty_ancestor_is_not_a_barrier(dotenv_family):
    Parent, _, _, child_file, _ = dotenv_family

    class Middle(Parent):
        model_config = SettingsConfigDict(env_file=None)

    class Child(Middle):
        model_config = SettingsConfigDict(env_file=child_file, env_file_inherit=True)

    assert Child().parent_value == 1
    assert Child().child_value == 2
