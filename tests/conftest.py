import os

import pytest


class SetEnv:
    def __init__(self):
        self.envars = set()

    def set(self, name, value):
        self.envars.add(name)
        os.environ[name] = value

    def pop(self, name):
        self.envars.remove(name)
        os.environ.pop(name)

    def clear(self):
        for n in self.envars:
            os.environ.pop(n)


@pytest.fixture
def env():
    setenv = SetEnv()

    yield setenv

    setenv.clear()


@pytest.fixture
def docs_test_env():
    setenv = SetEnv()

    # envs for basic usage example
    setenv.set('my_auth_key', 'xxx')
    setenv.set('my_api_key', 'xxx')

    # envs for parsing environment variable values example
    setenv.set('V0', '0')
    setenv.set('SUB_MODEL', '{"v1": "json-1", "v2": "json-2"}')
    setenv.set('SUB_MODEL__V2', 'nested-2')
    setenv.set('SUB_MODEL__V3', '3')
    setenv.set('SUB_MODEL__DEEP__V4', 'v4')

    yield setenv

    setenv.clear()
