from typing import Annotated

from annotated_types import MinLen

from pydantic_settings import BaseSettings

try:
    import dotenv
except ImportError:
    dotenv = None


def test_annotated_with_type(env):
    type MinLenList = Annotated[list[str], MinLen(2)]

    class AnnotatedComplexSettings(BaseSettings):
        apples: MinLenList

    env.set('apples', '["russet", "granny smith"]')
    s = AnnotatedComplexSettings()
    assert s.apples == ['russet', 'granny smith']
