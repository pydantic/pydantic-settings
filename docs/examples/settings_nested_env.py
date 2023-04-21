from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings


class DeepSubModel(BaseModel):
    v4: str


class SubModel(BaseModel):
    v1: str
    v2: bytes
    v3: int
    deep: DeepSubModel


class Settings(BaseSettings):
    v0: str
    sub_model: SubModel

    model_config = ConfigDict(env_nested_delimiter='__')


print(Settings().model_dump())
