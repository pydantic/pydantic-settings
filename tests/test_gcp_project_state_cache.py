from types import SimpleNamespace

import pytest
from pytest_mock import MockerFixture

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource
from pydantic_settings.sources.providers.gcp import GoogleSecretManagerSettingsSource, import_gcp_secret_manager

try:
    import_gcp_secret_manager()
    from google.cloud.secretmanager import SecretManagerServiceClient

    gcp_available = True
except ImportError:
    gcp_available = False

pytestmark = pytest.mark.skipif(not gcp_available, reason='Google Secret Manager dependency unavailable')


@pytest.mark.parametrize('explicit_project', [None, 'explicit-project'])
def test_reused_source_tracks_project_from_previous_settings_sources(
    mocker: MockerFixture, explicit_project: str | None
) -> None:
    client = mocker.Mock(spec=SecretManagerServiceClient)
    client.secret_version_path.side_effect = SecretManagerServiceClient.secret_version_path

    def read_secret(*, name: str) -> SimpleNamespace:
        return SimpleNamespace(payload=SimpleNamespace(data=name.split('/')[1].encode()))

    client.access_secret_version.side_effect = read_secret
    auth = mocker.patch('pydantic_settings.sources.providers.gcp.google_auth_default')

    class Settings(BaseSettings):
        project_id: str
        password: str

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return init_settings, source

    source = GoogleSecretManagerSettingsSource(Settings, secret_client=client, project_id=explicit_project)
    first = Settings(project_id='first-project')
    second = Settings(project_id='second-project')
    assert first.password == (explicit_project or 'first-project')
    assert second.password == (explicit_project or 'second-project')
    auth.assert_not_called()


def test_project_cache_is_invalidated_when_previous_source_project_disappears(mocker: MockerFixture) -> None:
    client = mocker.Mock(spec=SecretManagerServiceClient)
    client.secret_version_path.side_effect = SecretManagerServiceClient.secret_version_path

    def read_secret(*, name: str) -> SimpleNamespace:
        return SimpleNamespace(payload=SimpleNamespace(data=name.split('/')[1].encode()))

    client.access_secret_version.side_effect = read_secret
    auth = mocker.patch(
        'pydantic_settings.sources.providers.gcp.google_auth_default', return_value=(None, 'default-project')
    )

    class Settings(BaseSettings):
        password: str

    source = GoogleSecretManagerSettingsSource(Settings, secret_client=client, project_id_field='GCP_PROJECT')
    assert source()['password'] == 'default-project'
    assert source()['password'] == 'default-project'
    auth.assert_called_once()
    source._set_current_state({'GCP_PROJECT': 'state-project'})
    assert source()['password'] == 'state-project'
    source._set_current_state({})
    assert source()['password'] == 'default-project'
    assert auth.call_count == 2
