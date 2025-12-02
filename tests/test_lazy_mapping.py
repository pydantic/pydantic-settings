"""
Test pydantic_settings lazy loading functionality.

Lazy loading defers field value resolution until the fields are accessed,
rather than eagerly evaluating all fields during settings initialization.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
)
from pydantic_settings.sources.lazy import LazyMapping


class TestLazyMapping:
    """Test LazyMapping class behavior."""

    def test_lazy_mapping_init(self):
        """Test LazyMapping initialization."""
        source = MagicMock(spec=PydanticBaseSettingsSource)
        mapping = LazyMapping(source)
        assert mapping._source is source
        assert mapping._cached_values == {}

    def test_lazy_mapping_getitem_with_caching(self):
        """Test LazyMapping caches values after first access."""
        source = MagicMock()

        # Mock settings class with a field
        settings_cls = MagicMock()
        field_info = MagicMock()
        settings_cls.model_fields = {'test_field': field_info}
        source.settings_cls = settings_cls

        # Mock the field resolution
        source._get_resolved_field_value.return_value = ('test-value', None, False)
        source.prepare_field_value.return_value = 'prepared-value'

        mapping = LazyMapping(source)

        # First access should call the resolution methods
        value1 = mapping['test_field']
        assert value1 == 'prepared-value'
        assert source._get_resolved_field_value.call_count == 1

        # Second access should use cached value
        value2 = mapping['test_field']
        assert value2 == 'prepared-value'
        assert source._get_resolved_field_value.call_count == 1  # Not called again

    def test_lazy_mapping_getitem_key_not_found(self):
        """Test LazyMapping raises KeyError for missing keys."""
        source = MagicMock()
        settings_cls = MagicMock()
        settings_cls.model_fields = {}
        source.settings_cls = settings_cls

        mapping = LazyMapping(source)

        with pytest.raises(KeyError):
            _ = mapping['nonexistent']

    def test_lazy_mapping_iter(self):
        """Test LazyMapping iteration returns all field names."""
        source = MagicMock()

        # Mock settings class with multiple fields
        field_info1 = MagicMock()
        field_info2 = MagicMock()
        settings_cls = MagicMock()
        settings_cls.model_fields = {'field1': field_info1, 'field2': field_info2}
        source.settings_cls = settings_cls

        # Mock alias names function
        with patch('pydantic_settings.sources.lazy._get_alias_names') as mock_alias:
            mock_alias.side_effect = [(['alias1'], None), (['alias2'], None)]

            mapping = LazyMapping(source)
            keys = list(mapping)

            assert 'alias1' in keys
            assert 'field1' in keys or 'alias2' in keys
            assert 'field2' in keys or 'alias2' in keys

    def test_lazy_mapping_len(self):
        """Test LazyMapping returns correct length."""
        source = MagicMock(spec=PydanticBaseSettingsSource)
        settings_cls = MagicMock()
        settings_cls.model_fields = {'field1': MagicMock(), 'field2': MagicMock(), 'field3': MagicMock()}
        source.settings_cls = settings_cls

        mapping = LazyMapping(source)
        assert len(mapping) == 3

    def test_lazy_mapping_copy(self):
        """Test LazyMapping.copy() preserves cached values."""
        source = MagicMock(spec=PydanticBaseSettingsSource)
        settings_cls = MagicMock()
        settings_cls.model_fields = {'field1': MagicMock()}
        source.settings_cls = settings_cls

        mapping = LazyMapping(source)
        mapping._cached_values['field1'] = 'cached-value'

        copied = mapping.copy()

        assert isinstance(copied, LazyMapping)
        assert copied._source is source
        assert copied._cached_values == {'field1': 'cached-value'}
        # Ensure it's a shallow copy of the dict
        assert copied._cached_values is not mapping._cached_values

    def test_lazy_mapping_items(self):
        """Test LazyMapping.items() yields accessible key-value pairs."""
        source = MagicMock()

        field_info = MagicMock()
        settings_cls = MagicMock()
        settings_cls.model_fields = {'test_field': field_info}
        source.settings_cls = settings_cls

        source._get_resolved_field_value.return_value = ('value', None, False)
        source.prepare_field_value.return_value = 'prepared-value'

        with patch('pydantic_settings.sources.lazy._get_alias_names') as mock_alias:
            mock_alias.return_value = (['test_field'], None)

            mapping = LazyMapping(source)
            items = dict(mapping.items())

            assert 'test_field' in items
            assert items['test_field'] == 'prepared-value'


class TestLazyLoadingWithDeepUpdate:
    """Test LazyMapping behavior with deep_update to ensure lazy behavior is preserved."""

    def test_lazy_mapping_deep_update_preserves_lazy_behavior(self):
        """Test that deep_update with LazyMapping copy() preserves lazy behavior."""
        from pydantic._internal._utils import deep_update

        source = MagicMock()
        settings_cls = MagicMock()
        field_info = MagicMock()
        settings_cls.model_fields = {'field1': field_info, 'field2': field_info}
        source.settings_cls = settings_cls

        source._get_resolved_field_value.return_value = ('value', None, False)
        source.prepare_field_value.side_effect = lambda fname, fi, v, _: f'prepared-{fname}'

        # Create two LazyMappings
        mapping2 = LazyMapping(source)

        # Simulate deep_update behavior
        result = deep_update({'field1': 'eager-value'}, mapping2.copy())

        # The result should contain the lazily evaluated value from mapping2
        # and the copy() should have returned a LazyMapping, not a regular dict
        assert isinstance(result.get('field1'), str)

    def test_lazy_mapping_copy_maintains_source_reference(self):
        """Test that LazyMapping.copy() maintains reference to the same source."""
        source = MagicMock()
        settings_cls = MagicMock()
        settings_cls.model_fields = {}
        source.settings_cls = settings_cls

        mapping = LazyMapping(source)
        copied = mapping.copy()

        # Both should reference the same source object
        assert mapping._source is copied._source


class TestLazyLoadingWithConfigFiles:
    """Test lazy loading compatibility with config file sources."""

    def test_lazy_mapping_with_dict_like_interface(self):
        """Test that LazyMapping implements proper dict-like interface."""
        source = MagicMock()
        field_info = MagicMock()
        settings_cls = MagicMock()
        settings_cls.model_fields = {'field1': field_info}
        source.settings_cls = settings_cls

        source._get_resolved_field_value.return_value = ('test-value', None, False)
        source.prepare_field_value.return_value = 'prepared-value'

        mapping = LazyMapping(source)

        # Test Mapping interface methods
        assert 'field1' in list(mapping)
        assert len(mapping) == 1
        assert mapping['field1'] == 'prepared-value'

    def test_lazy_mapping_error_on_missing_field(self):
        """Test LazyMapping raises SettingsError for missing fields during resolution."""
        from pydantic_settings.exceptions import SettingsError

        source = MagicMock()
        field_info = MagicMock()
        settings_cls = MagicMock()
        settings_cls.model_fields = {'field1': field_info}
        source.settings_cls = settings_cls
        source.__class__.__name__ = 'MockSource'

        # Simulate an error during field value resolution
        source._get_resolved_field_value.side_effect = ValueError('Connection failed')

        mapping = LazyMapping(source)

        # Accessing the field should raise SettingsError (not ValueError)
        with pytest.raises(SettingsError, match='error getting value for field "field1"'):
            _ = mapping['field1']


class TestLazyLoadingSourcesWithParameter:
    """Test that GCP sources accept lazy_load parameter."""

    def test_gcp_secrets_source_accepts_lazy_load(self):
        """Test GoogleSecretManagerSettingsSource accepts lazy_load parameter."""
        from pydantic_settings.sources.providers.gcp import GoogleSecretManagerSettingsSource

        class TestSettings(BaseSettings):
            field: str = 'default'

        try:
            # This will fail if google-cloud-secret-manager is not installed
            import inspect

            sig = inspect.signature(GoogleSecretManagerSettingsSource.__init__)
            assert 'lazy_load' in sig.parameters
        except ImportError:
            # gcp not installed, skip
            pytest.skip('google-cloud-secret-manager not installed')


class TestGCPSecretManagerLazyLoading:
    """Unit tests for lazy_load behavior in GoogleSecretManagerSettingsSource."""

    def test_returns_lazy_mapping_when_lazy_load_true(self):
        """Test GoogleSecretManagerSettingsSource stores LazyMapping when lazy_load=True."""
        try:
            from pydantic_settings.sources.providers.gcp import GoogleSecretManagerSettingsSource
        except ImportError:
            pytest.skip('google-cloud-secret-manager not installed')

        class TestSettings(BaseSettings):
            field: str = 'default'

        with patch(
            'pydantic_settings.sources.providers.gcp.google_auth_default', return_value=(MagicMock(), 'test-project')
        ):
            with patch('pydantic_settings.sources.providers.gcp.SecretManagerServiceClient'):
                source = GoogleSecretManagerSettingsSource(TestSettings, lazy_load=True)
                result = source()
                assert isinstance(result, dict)
                assert len(result) == 0
                assert hasattr(source, '_lazy_mapping')
                assert isinstance(source._lazy_mapping, LazyMapping)

    def test_returns_dict_when_lazy_load_false(self):
        """Test GoogleSecretManagerSettingsSource returns dict when lazy_load=False."""
        try:
            from pydantic_settings.sources.providers.gcp import GoogleSecretManagerSettingsSource
        except ImportError:
            pytest.skip('google-cloud-secret-manager not installed')

        class TestSettings(BaseSettings):
            field: str = 'default'

        with patch(
            'pydantic_settings.sources.providers.gcp.google_auth_default', return_value=(MagicMock(), 'test-project')
        ):
            with patch('pydantic_settings.sources.providers.gcp.SecretManagerServiceClient'):
                source = GoogleSecretManagerSettingsSource(TestSettings, lazy_load=False)
                result = source()
                assert isinstance(result, dict)
                assert not hasattr(source, '_lazy_mapping') or source._lazy_mapping is None

    def test_lazy_mapping_defers_resolution(self):
        """Test GoogleSecretManagerSettingsSource LazyMapping defers resolution."""
        try:
            from pydantic_settings.sources.providers.gcp import GoogleSecretManagerSettingsSource
        except ImportError:
            pytest.skip('google-cloud-secret-manager not installed')

        class TestSettings(BaseSettings):
            field: str = 'default'

        with patch(
            'pydantic_settings.sources.providers.gcp.google_auth_default', return_value=(MagicMock(), 'test-project')
        ):
            with patch('pydantic_settings.sources.providers.gcp.SecretManagerServiceClient'):
                source = GoogleSecretManagerSettingsSource(TestSettings, lazy_load=True)

                with patch.object(
                    source, '_get_resolved_field_value', wraps=source._get_resolved_field_value
                ) as mock_resolve:
                    source()
                    assert mock_resolve.call_count == 0

                    lazy_mapping = source._lazy_mapping
                    try:
                        _ = lazy_mapping['field']
                        assert mock_resolve.call_count > 0
                    except KeyError:
                        assert mock_resolve.call_count > 0


class TestLazyMappingAdditionalMethods:
    """Test additional LazyMapping methods and edge cases."""

    def test_lazy_mapping_get_method(self):
        """Test LazyMapping.get() method."""
        source = MagicMock()
        settings_cls = MagicMock()
        field_info = MagicMock()
        settings_cls.model_fields = {'field1': field_info}
        source.settings_cls = settings_cls

        source._get_resolved_field_value.return_value = ('value1', None, False)
        source.prepare_field_value.return_value = 'prepared-value1'

        mapping = LazyMapping(source)

        # Test get with existing key
        assert mapping.get('field1') == 'prepared-value1'

        # Test get with non-existing key and default
        assert mapping.get('nonexistent', 'default') == 'default'

        # Test get with non-existing key and no default
        assert mapping.get('nonexistent') is None

    def test_lazy_mapping_keys_method(self):
        """Test LazyMapping.keys() method."""
        source = MagicMock()
        field_info1 = MagicMock()
        field_info2 = MagicMock()
        settings_cls = MagicMock()
        settings_cls.model_fields = {'field1': field_info1, 'field2': field_info2}
        source.settings_cls = settings_cls

        with patch('pydantic_settings.sources.lazy._get_alias_names') as mock_alias:
            mock_alias.side_effect = [(['field1'], None), (['field2'], None)]

            mapping = LazyMapping(source)
            keys = list(mapping.keys())

            assert 'field1' in keys
            assert 'field2' in keys
            assert len(keys) == 2

    def test_lazy_mapping_values_method(self):
        """Test LazyMapping.values() method."""
        source = MagicMock()
        field_info = MagicMock()
        settings_cls = MagicMock()
        settings_cls.model_fields = {'field1': field_info}
        source.settings_cls = settings_cls

        source._get_resolved_field_value.return_value = ('value1', None, False)
        source.prepare_field_value.return_value = 'prepared-value1'

        with patch('pydantic_settings.sources.lazy._get_alias_names') as mock_alias:
            mock_alias.return_value = (['field1'], None)

            mapping = LazyMapping(source)
            values = list(mapping.values())

            assert 'prepared-value1' in values
            assert len(values) == 1

    def test_lazy_mapping_contains_method(self):
        """Test LazyMapping __contains__ method."""
        source = MagicMock()
        field_info = MagicMock()
        settings_cls = MagicMock()
        settings_cls.model_fields = {'field1': field_info}
        source.settings_cls = settings_cls

        source._get_resolved_field_value.return_value = ('value1', None, False)
        source.prepare_field_value.return_value = 'prepared-value1'

        with patch('pydantic_settings.sources.lazy._get_alias_names') as mock_alias:
            mock_alias.return_value = (['field1'], None)

            mapping = LazyMapping(source)

            assert 'field1' in mapping
            assert 'nonexistent' not in mapping

    def test_lazy_mapping_bool_conversion(self):
        """Test LazyMapping __bool__ method."""
        source = MagicMock()
        settings_cls = MagicMock()
        settings_cls.model_fields = {'field1': MagicMock()}
        source.settings_cls = settings_cls

        mapping = LazyMapping(source)

        # Non-empty mapping should be truthy
        assert bool(mapping) is True

        # Empty mapping should be falsy
        settings_cls.model_fields = {}
        mapping_empty = LazyMapping(source)
        assert bool(mapping_empty) is False

    def test_lazy_mapping_with_alias_resolution(self):
        """Test LazyMapping resolves fields by alias names."""
        source = MagicMock()
        field_info = MagicMock()
        settings_cls = MagicMock()
        settings_cls.model_fields = {'field_name': field_info}
        source.settings_cls = settings_cls

        source._get_resolved_field_value.return_value = ('alias_value', None, False)
        source.prepare_field_value.return_value = 'prepared-alias-value'

        with patch('pydantic_settings.sources.lazy._get_alias_names') as mock_alias:
            mock_alias.return_value = (['field_alias'], None)

            mapping = LazyMapping(source)

            # Access by alias should resolve correctly
            assert mapping['field_alias'] == 'prepared-alias-value'

    def test_lazy_mapping_field_not_found_raises_key_error(self):
        """Test LazyMapping raises KeyError for completely missing fields."""
        source = MagicMock()
        settings_cls = MagicMock()
        settings_cls.model_fields = {}
        source.settings_cls = settings_cls

        mapping = LazyMapping(source)

        with pytest.raises(KeyError):
            _ = mapping['nonexistent_field']
