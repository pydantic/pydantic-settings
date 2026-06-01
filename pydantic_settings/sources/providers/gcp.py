from __future__ import annotations as _annotations

import warnings
from collections.abc import Iterator, Mapping
from functools import cached_property
from typing import TYPE_CHECKING, Any

from pydantic.fields import FieldInfo

from ..types import SecretVersion
from .env import EnvSettingsSource

if TYPE_CHECKING:
    from google.auth import default as google_auth_default
    from google.auth.credentials import Credentials
    from google.cloud.secretmanager import SecretManagerServiceClient

    from pydantic_settings.main import BaseSettings
else:
    Credentials = None
    SecretManagerServiceClient = None
    google_auth_default = None


def import_gcp_secret_manager() -> None:
    global Credentials
    global SecretManagerServiceClient
    global google_auth_default

    try:
        from google.auth import default as google_auth_default
        from google.auth.credentials import Credentials

        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=FutureWarning)
            from google.cloud.secretmanager import SecretManagerServiceClient
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            'GCP Secret Manager dependencies are not installed, run `pip install pydantic-settings[gcp-secret-manager]`'
        ) from e


def _is_not_found_error(exc: Exception) -> bool:
    try:
        from google.api_core.exceptions import NotFound

        return isinstance(exc, NotFound)
    except ImportError:
        return False


class GoogleSecretManagerMapping(Mapping[str, str | None]):
    _loaded_secrets: dict[str, str | None]
    _secret_client: SecretManagerServiceClient

    def __init__(self, secret_client: SecretManagerServiceClient, project_id: str, case_sensitive: bool) -> None:
        self._loaded_secrets = {}
        self._secret_client = secret_client
        self._project_id = project_id
        self._case_sensitive = case_sensitive

    @property
    def _gcp_project_path(self) -> str:
        return self._secret_client.common_project_path(self._project_id)

    def _select_case_insensitive_secret(self, lower_name: str, candidates: list[str]) -> str:
        if len(candidates) == 1:
            return candidates[0]

        # Sort to ensure deterministic selection (prefer lowercase / ASCII last)
        candidates.sort()
        winner = candidates[-1]
        warnings.warn(
            f"Secret collision: Found multiple secrets {candidates} normalizing to '{lower_name}'. "
            f"Using '{winner}' for case-insensitive lookup.",
            UserWarning,
            stacklevel=2,
        )
        return winner

    @cached_property
    def _secret_name_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        # Group secrets by normalized name to detect collisions
        normalized_groups: dict[str, list[str]] = {}

        secrets = self._secret_client.list_secrets(parent=self._gcp_project_path)
        for secret in secrets:
            name = self._secret_client.parse_secret_path(secret.name).get('secret', '')
            mapping[name] = name

            if not self._case_sensitive:
                lower_name = name.lower()
                if lower_name not in normalized_groups:
                    normalized_groups[lower_name] = []
                normalized_groups[lower_name].append(name)

        if not self._case_sensitive:
            for lower_name, candidates in normalized_groups.items():
                mapping[lower_name] = self._select_case_insensitive_secret(lower_name, candidates)

        return mapping

    @property
    def _secret_names(self) -> list[str]:
        return list(self._secret_name_map.keys())

    def _secret_version_path(self, key: str, version: str = 'latest') -> str:
        return self._secret_client.secret_version_path(self._project_id, key, version)

    def _get_secret_value(self, gcp_secret_name: str, version: str = 'latest') -> str | None:
        try:
            return self._secret_client.access_secret_version(
                name=self._secret_version_path(gcp_secret_name, version)
            ).payload.data.decode('UTF-8')
        except Exception:
            return None

    def _get_secret_value_or_raise(self, gcp_secret_name: str) -> str | None:
        try:
            return self._secret_client.access_secret_version(
                name=self._secret_version_path(gcp_secret_name)
            ).payload.data.decode('UTF-8')
        except Exception as e:
            if _is_not_found_error(e):
                raise KeyError(gcp_secret_name) from e
            return None

    def __getitem__(self, key: str) -> str | None:
        if key in self._loaded_secrets:
            return self._loaded_secrets[key]

        if self._case_sensitive:
            self._loaded_secrets[key] = self._get_secret_value_or_raise(key)
            return self._loaded_secrets[key]

        gcp_secret_name = self._secret_name_map.get(key)
        if gcp_secret_name is None:
            gcp_secret_name = self._secret_name_map.get(key.lower())

        if gcp_secret_name:
            self._loaded_secrets[key] = self._get_secret_value(gcp_secret_name)
        else:
            raise KeyError(key)

        return self._loaded_secrets[key]

    def __len__(self) -> int:
        return len(self._secret_names)

    def __iter__(self) -> Iterator[str]:
        return iter(self._secret_names)


class GoogleSecretManagerSettingsSource(EnvSettingsSource):
    _credentials: Credentials | None
    _secret_client: SecretManagerServiceClient | None
    _project_id: str | None
    _explicit_project_id: str | None

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        credentials: Credentials | None = None,
        project_id: str | None = None,
        env_prefix: str | None = None,
        env_parse_none_str: str | None = None,
        env_parse_enums: bool | None = None,
        secret_client: SecretManagerServiceClient | None = None,
        case_sensitive: bool | None = True,
        project_id_field: str = 'project_id',
    ) -> None:
        """Settings source that reads secrets from Google Cloud Secret Manager.

        Args:
            project_id: The GCP project to read secrets from. If not provided, it is
                resolved lazily (see below).
            project_id_field: The key, populated by a previous (higher priority)
                settings source, to use as the ``project_id`` when one is not passed
                explicitly. This is the model field name — or its preferred alias when
                a ``validation_alias`` is set — under which the project ID is exposed by
                the previous source, NOT an environment variable name. For example with
                ``some_field: str = Field(alias='GCP_PROJECT')`` set ``project_id_field``
                to ``'GCP_PROJECT'``. Defaults to ``'project_id'``.

        The ``project_id`` is resolved lazily in :meth:`__call__` rather than at
        construction time so that it can be sourced from settings resolved by previous
        sources (only available via ``current_state`` once the source is called).
        Resolution order is:

        1. the explicit ``project_id`` argument
        2. the ``project_id_field`` value from previous settings sources
        3. ``google.auth.default()``
        """
        # Import Google Packages if they haven't already been imported
        if SecretManagerServiceClient is None or Credentials is None or google_auth_default is None:
            import_gcp_secret_manager()

        # Resolution is deferred to __call__ (see _resolve_gcp_project / _load_env_vars).
        # _explicit_project_id is the immutable user input; _project_id is the resolved
        # value and is written exclusively by _resolve_gcp_project.
        self._explicit_project_id = project_id
        self._project_id = None
        self._credentials = credentials
        self._secret_client = secret_client
        self._project_id_field = project_id_field
        self._env_vars_loaded = False

        super().__init__(
            settings_cls,
            case_sensitive=case_sensitive,
            env_prefix=env_prefix,
            env_ignore_empty=False,
            env_parse_none_str=env_parse_none_str,
            env_parse_enums=env_parse_enums,
        )
        # __init__ is past; subsequent _load_env_vars() calls may now resolve the project.
        self._env_vars_loaded = True

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        """Override get_field_value to get the secret value from GCP Secret Manager.
        Look for a SecretVersion metadata field to specify a particular SecretVersion.

        Args:
            field: The field to get the value for
            field_name: The declared name of the field

        Returns:
            A tuple of (value, key, value_is_complex), where `key` is the identifier used
            to populate the model (either the field name or an alias, depending on
            configuration).
        """

        secret_version = next((m.version for m in field.metadata if isinstance(m, SecretVersion)), None)

        # If a secret version is specified, try to get that specific version of the secret from
        # GCP Secret Manager via the GoogleSecretManagerMapping. This allows different versions
        # of the same secret name to be retrieved independently and cached in the GoogleSecretManagerMapping
        if secret_version and isinstance(self.env_vars, GoogleSecretManagerMapping):
            for field_key, env_name, value_is_complex in self._extract_field_info(field, field_name):
                if self.case_sensitive:
                    gcp_secret_name: str | None = env_name
                else:
                    gcp_secret_name = self.env_vars._secret_name_map.get(env_name)
                    if gcp_secret_name is None:
                        gcp_secret_name = self.env_vars._secret_name_map.get(env_name.lower())

                if gcp_secret_name:
                    env_val = self.env_vars._get_secret_value(gcp_secret_name, secret_version)
                    if env_val is not None:
                        # If populate_by_name is enabled, return field_name to allow multiple fields
                        # with the same alias but different versions to be distinguished
                        if self.settings_cls.model_config.get('populate_by_name'):
                            return env_val, field_name, value_is_complex
                        return env_val, field_key, value_is_complex

            # If a secret version is specified but not found, we should not fall back to "latest" (default behavior)
            # as that would be incorrect. We return None to indicate the value was not found.
            return None, field_name, False

        val, key, is_complex = super().get_field_value(field, field_name)

        # If populate_by_name is enabled, we need to return the field_name as the key
        # without this being enabled, you cannot load two secrets with the same name but different versions
        if self.settings_cls.model_config.get('populate_by_name') and val is not None:
            return val, field_name, is_complex
        return val, key, is_complex

    def _resolve_gcp_project(self) -> None:
        """Resolve the credentials, project_id and Secret Manager client.

        ``project_id`` is resolved, in order of precedence, from: the explicit
        ``project_id`` argument, the ``project_id_field`` value from previous settings
        sources (``current_state``), and finally ``google.auth.default()``.
        """
        project_id = self._explicit_project_id
        credentials = self._credentials

        # Fall back to a value resolved by a previous (higher priority) settings source.
        if project_id is None:
            state_project_id = self.current_state.get(self._project_id_field)
            if isinstance(state_project_id, str):
                project_id = state_project_id

        # Fall back to google.auth.default for whatever is still missing.
        # Credentials are only needed if we have to build a client ourselves — if the
        # caller supplied a pre-built secret_client we can skip the auth call entirely
        # when project_id is also known, avoiding an unnecessary RPC / file read.
        need_credentials = self._secret_client is None and credentials is None
        need_project = project_id is None
        if need_credentials or need_project:
            _creds, _project_id = google_auth_default()
            if need_credentials:
                credentials = _creds
            if need_project and isinstance(_project_id, str):
                project_id = _project_id

        if project_id is None:
            raise AttributeError(
                'project_id is required to be specified either as an argument, via a previous '
                'settings source, or from google.auth.default. See '
                'https://google-auth.readthedocs.io/en/master/reference/google.auth.html#google.auth.default'
            )

        self._credentials = credentials
        self._project_id = project_id
        if self._secret_client is None:
            self._secret_client = SecretManagerServiceClient(credentials=self._credentials)

    def _load_env_vars(self) -> Mapping[str, str | None]:
        # During __init__ the previous sources have not run yet, so defer building the
        # mapping until __call__, where current_state (and thus project_id) is available.
        if not self._env_vars_loaded:
            return {}

        self._resolve_gcp_project()
        assert self._project_id is not None and self._secret_client is not None
        return GoogleSecretManagerMapping(
            self._secret_client, project_id=self._project_id, case_sensitive=self.case_sensitive
        )

    def __call__(self) -> dict[str, Any]:
        # current_state is populated by previous sources right before __call__; (re)build
        # the mapping now so project_id can be sourced from them.
        self._env_vars_loaded = True
        self.env_vars = self._load_env_vars()
        return super().__call__()

    def __repr__(self) -> str:
        # Prefer the resolved project_id, falling back to the explicit constructor
        # arg so the repr is informative before the source has been called.
        project_id = self._project_id if self._project_id is not None else self._explicit_project_id
        return (
            f'{self.__class__.__name__}(project_id={project_id!r}, env_nested_delimiter={self.env_nested_delimiter!r})'
        )


__all__ = ['GoogleSecretManagerSettingsSource', 'GoogleSecretManagerMapping']
