"""XML settings source"""

from __future__ import annotations as _annotations

import xml.etree.ElementTree as ET
from typing import (
    TYPE_CHECKING,
    Any,
)

from ..base import ConfigFileSourceMixin, InitSettingsSource
from ..types import DEFAULT_PATH, ConfigFileSourceType
from ..utils import InitState, _xml_to_dict

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic_settings.main import BaseSettings

    from ..types import Traversable


class XmlConfigSettingsSource(InitSettingsSource, ConfigFileSourceMixin):
    """
    A source class that loads variables from a xml file
    """

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        xml_file: ConfigFileSourceType | None = DEFAULT_PATH,
        xml_file_encoding: str | None = None,
        xml_attr_prefix: str | None = None,
        xml_text_key: str | None = None,
        xml_strip_namespaces: bool | None = None,
        xml_strip_whitespace: bool | None = None,
        xml_empty_as_none: bool | None = None,
        xml_force_list: str | None = None,
        deep_merge: bool = False,
        _init_state: InitState | None = None,
    ):
        self.xml_file = xml_file if xml_file != DEFAULT_PATH else settings_cls.model_config.get('xml_file')
        self.xml_file_encoding = (
            xml_file_encoding if xml_file_encoding is not None else settings_cls.model_config.get('xml_file_encoding')
        )

        self.xml_attr_prefix = (
            xml_attr_prefix if xml_attr_prefix is not None else settings_cls.model_config.get('xml_attr_prefix', '')
        )
        self.xml_text_key = (
            xml_text_key if xml_text_key is not None else settings_cls.model_config.get('xml_text_key', 'value')
        )
        self.xml_strip_namespaces = (
            xml_strip_namespaces
            if xml_strip_namespaces is not None
            else settings_cls.model_config.get('xml_strip_namespaces', True)
        )
        self.xml_strip_whitespace = (
            xml_strip_whitespace
            if xml_strip_whitespace is not None
            else settings_cls.model_config.get('xml_strip_whitespace', True)
        )
        self.xml_empty_as_none = (
            xml_empty_as_none
            if xml_empty_as_none is not None
            else settings_cls.model_config.get('xml_empty_as_none', True)
        )
        self.xml_force_list = (
            xml_force_list if xml_force_list is not None else settings_cls.model_config.get('xml_force_list')
        )

        self.xml_data = self._read_files(self.xml_file, deep_merge=deep_merge)
        super().__init__(settings_cls, self.xml_data, _init_state=_init_state)

    def _read_file(self, path: Path | Traversable) -> dict[str, Any]:
        with path.open(encoding=self.xml_file_encoding) as xml_file:
            content = xml_file.read()

        root = ET.fromstring(content)
        return _xml_to_dict(
            root,
            attr_prefix=self.xml_attr_prefix,
            text_key=self.xml_text_key,
            strip_namespaces=self.xml_strip_namespaces,
            strip_whitespace=self.xml_strip_whitespace,
            empty_as_none=self.xml_empty_as_none,
            force_list=self.xml_force_list,
        )

    def __repr__(self) -> str:
        return (
            f'{self.__class__.__name__}(xml_file={self.xml_file}, xml_file_encoding={self.xml_file_encoding!r}, '
            f'xml_attr_prefix={self.xml_attr_prefix!r}, xml_text_key={self.xml_text_key!r}, '
            f'xml_strip_namespaces={self.xml_strip_namespaces!r}, xml_strip_whitespace={self.xml_strip_whitespace!r}, '
            f'xml_empty_as_none={self.xml_empty_as_none!r}, xml_force_list={self.xml_force_list!r})'
        )
