from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_host: str = 'localhost'

    model_config = ConfigDict(case_sensitive=True)
