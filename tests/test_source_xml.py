import importlib
import sys
import xml.etree.ElementTree as ET
import zipfile
from importlib.resources import files
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    XmlConfigSettingsSource,
)
from pydantic_settings.exceptions import SettingsError


def test_repr() -> None:
    source = XmlConfigSettingsSource(BaseSettings, Path('config.xml'))
    assert repr(source) == (
        'XmlConfigSettingsSource(xml_file=config.xml, xml_file_encoding=None, '
        "xml_attr_prefix='', xml_text_key='value', xml_strip_namespaces=True, "
        'xml_strip_whitespace=True, xml_empty_as_none=True, xml_force_list=None)'
    )


def test_xml_file(tmp_path):
    p = tmp_path / 'test.xml'
    p.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
        <settings app_name="myapp" debug="true">
            <host>127.0.0.1</host>
            <port>8000</port>
            <database user="admin">
                <host>db.local</host>
                <port>5432</port>
            </database>
            <allowed_hosts>
                <host>a.example.com</host>
                <host>b.example.com</host>
            </allowed_hosts>
            <empty></empty>
        </settings>
        """
    )

    class Database(BaseModel):
        user: str
        host: str
        port: int

    class AllowedHosts(BaseModel):
        host: list[str]

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(xml_file=p)

        app_name: str
        debug: bool
        host: str
        port: int
        database: Database
        allowed_hosts: AllowedHosts
        empty: str | None = None

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (XmlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {
        'app_name': 'myapp',
        'debug': True,
        'host': '127.0.0.1',
        'port': 8000,
        'database': {'user': 'admin', 'host': 'db.local', 'port': 5432},
        'allowed_hosts': {'host': ['a.example.com', 'b.example.com']},
        'empty': None,
    }


def test_xml_no_file():
    class Settings(BaseSettings):
        model_config = SettingsConfigDict(xml_file=None)

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (XmlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {}


def test_xml_file_missing(tmp_path):
    p = tmp_path / 'does-not-exist.xml'

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(xml_file=p)

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (XmlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {}


def test_multiple_file_xml(tmp_path):
    p1 = tmp_path / 'test1.xml'
    p2 = tmp_path / 'test2.xml'
    p1.write_text('<settings><xml1>1</xml1></settings>')
    p2.write_text('<settings><xml2>2</xml2></settings>')

    class Settings(BaseSettings):
        xml1: int
        xml2: int

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (XmlConfigSettingsSource(settings_cls, xml_file=[p1, p2]),)

    s = Settings()
    assert s.model_dump() == {'xml1': 1, 'xml2': 2}


@pytest.mark.parametrize('deep_merge', [False, True])
def test_multiple_file_xml_merge(tmp_path, deep_merge):
    p1 = tmp_path / 'test1.xml'
    p2 = tmp_path / 'test2.xml'
    p1.write_text('<settings><hello>world</hello><nested foo="1" bar="2"/></settings>')
    p2.write_text('<settings><nested foo="3"/></settings>')

    class Nested(BaseModel):
        foo: int
        bar: int = 0

    class Settings(BaseSettings):
        hello: str
        nested: Nested

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (XmlConfigSettingsSource(settings_cls, xml_file=[p1, p2], deep_merge=deep_merge),)

    s = Settings()
    assert s.model_dump() == {'hello': 'world', 'nested': {'foo': 3, 'bar': 2 if deep_merge else 0}}


def test_xml_attr_prefix_and_text_key(tmp_path):
    p = tmp_path / 'test.xml'
    p.write_text('<settings><db driver="postgres"><host>db.local</host></db></settings>')

    class Db(BaseModel):
        driver: str = Field(alias='@driver')
        host: str

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(xml_file=p, xml_attr_prefix='@', xml_text_key='content')

        db: Db

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (XmlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {'db': {'driver': 'postgres', 'host': 'db.local'}}


def test_xml_attribute_element_collision(tmp_path):
    p = tmp_path / 'test.xml'
    p.write_text('<settings><db host="attr"><host>child</host></db></settings>')

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(xml_file=p)

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (XmlConfigSettingsSource(settings_cls),)

    with pytest.raises(SettingsError, match='host is defined both as an attribute and as a child element'):
        Settings()


@pytest.mark.parametrize('strip_namespaces', [True, False])
def test_xml_strip_namespaces(tmp_path, strip_namespaces):
    p = tmp_path / 'test.xml'
    p.write_text(
        '<settings xmlns:a="http://example.com/a" xmlns:b="http://example.com/b">'
        '<a:host>from-a</a:host>'
        '<b:host>from-b</b:host>'
        '</settings>'
    )

    class Stripped(BaseSettings):
        model_config = SettingsConfigDict(xml_file=p, xml_strip_namespaces=True)

        host: list[str]

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (XmlConfigSettingsSource(settings_cls),)

    class Kept(BaseSettings):
        model_config = SettingsConfigDict(xml_file=p, xml_strip_namespaces=False)

        host_a: str = Field(alias='{http://example.com/a}host')
        host_b: str = Field(alias='{http://example.com/b}host')

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (XmlConfigSettingsSource(settings_cls),)

    if strip_namespaces:
        # Same local name in two namespaces collapses into a single key.
        assert Stripped().model_dump() == {'host': ['from-a', 'from-b']}
    else:
        assert Kept().model_dump() == {'host_a': 'from-a', 'host_b': 'from-b'}


@pytest.mark.parametrize(
    'strip_whitespace, empty_as_none, blank, padded',
    [
        (True, True, None, 'hello'),
        (True, False, '', 'hello'),
        (False, True, None, '  hello  '),
        (False, False, '', '  hello  '),
    ],
)
def test_xml_whitespace_and_empty(tmp_path, strip_whitespace, empty_as_none, blank, padded):
    p = tmp_path / 'test.xml'
    p.write_text('<settings><blank></blank><spaces>   </spaces><padded>  hello  </padded></settings>')

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(
            xml_file=p,
            xml_strip_whitespace=strip_whitespace,
            xml_empty_as_none=empty_as_none,
        )

        blank: str | None
        spaces: str | None
        padded: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (XmlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {'blank': blank, 'spaces': blank, 'padded': padded}


def test_xml_force_list(tmp_path):
    p = tmp_path / 'test.xml'
    p.write_text('<settings><tags><tag>single</tag></tags><names><name>only</name></names></settings>')

    class Tags(BaseModel):
        tag: list[str]

    class Names(BaseModel):
        name: str

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(xml_file=p, xml_force_list=('tag',))

        tags: Tags
        names: Names

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (XmlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {'tags': {'tag': ['single']}, 'names': {'name': 'only'}}


def test_xml_force_list_matches_whole_tag_only(tmp_path):
    p = tmp_path / 'test.xml'
    p.write_text('<settings><tag>a</tag><ag>b</ag></settings>')

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(xml_file=p, xml_force_list=('tag',))

        tag: list[str]
        ag: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (XmlConfigSettingsSource(settings_cls),)

    s = Settings()
    assert s.model_dump() == {'tag': ['a'], 'ag': 'b'}


@pytest.mark.parametrize(
    'key, config_value, init_value',
    [
        ('xml_file_encoding', 'latin-1', 'utf-8'),
        ('xml_attr_prefix', '@', '#'),
        ('xml_text_key', 'text', 'content'),
        ('xml_strip_namespaces', False, True),
        ('xml_strip_whitespace', False, True),
        ('xml_empty_as_none', False, True),
        ('xml_force_list', ('a',), ('b',)),
    ],
)
def test_init_arg_overrides_model_config(tmp_path, key, config_value, init_value):
    p = tmp_path / 'test.xml'
    p.write_text('<settings/>')

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(xml_file=p, **{key: config_value})

    assert getattr(XmlConfigSettingsSource(Settings), key) == config_value
    assert getattr(XmlConfigSettingsSource(Settings, **{key: init_value}), key) == init_value


def test_xml_file_encoding(tmp_path):
    p = tmp_path / 'test.xml'
    p.write_bytes('<?xml version="1.0" encoding="cp1251"?><settings><name>Привет</name></settings>'.encode('cp1251'))

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(xml_file=p, xml_file_encoding='cp1251')

        name: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (XmlConfigSettingsSource(settings_cls),)

    assert Settings().model_dump() == {'name': 'Привет'}


def test_xml_ignores_comments_and_handles_cdata(tmp_path):
    p = tmp_path / 'test.xml'
    p.write_text('<settings><!-- a comment --><?some-pi data?><query><![CDATA[a < b & c]]></query></settings>')

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(xml_file=p)

        query: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (XmlConfigSettingsSource(settings_cls),)

    assert Settings().model_dump() == {'query': 'a < b & c'}


def test_xml_malformed(tmp_path):
    p = tmp_path / 'test.xml'
    p.write_text('<settings><unclosed></settings>')

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(xml_file=p)

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (XmlConfigSettingsSource(settings_cls),)

    with pytest.raises(ET.ParseError):
        Settings()


@pytest.fixture
def zip_traversable(tmp_path):
    created: list[str] = []

    def _make(pkg_name: str, filename: str, content: str):
        zip_path = tmp_path / f'{pkg_name}.zip'
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr(f'{pkg_name}/__init__.py', '')
            zf.writestr(f'{pkg_name}/{filename}', content)
        sys.path.insert(0, str(zip_path))
        importlib.invalidate_caches()
        created.append(pkg_name)
        trav = files(pkg_name).joinpath(filename)
        # Sanity check: a zip-packaged resource is not a filesystem ``Path``.
        assert not isinstance(trav, Path)
        return trav

    yield _make

    for pkg_name in created:
        sys.modules.pop(pkg_name, None)
        zip_str = str(tmp_path / f'{pkg_name}.zip')
        if zip_str in sys.path:
            sys.path.remove(zip_str)
    importlib.invalidate_caches()


def test_xml_file_traversable(zip_traversable):
    trav = zip_traversable('xml_trav_pkg', 'defaults.xml', '<settings><foobar>Hello</foobar></settings>')

    class Settings(BaseSettings):
        foobar: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (XmlConfigSettingsSource(settings_cls, xml_file=trav),)

    assert Settings().model_dump() == {'foobar': 'Hello'}
