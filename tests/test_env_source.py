from pydantic import BaseModel, Field

from pydantic_settings import BaseSettings, SettingsConfigDict


def test_env_source_when_load_multi_nested_config(env):
    # export my_prefix_llm__embeddings__openai__keys='["sk-..."]'
    # export my_prefix_llm__embeddings__qwen__keys='["sk-..."]'
    class EmbeddingModel(BaseModel):
        model: str = 'text-embedding-3-small'
        keys: list[str] = Field(default_factory=list)

    class LLM(BaseModel):
        embeddings: dict[str, EmbeddingModel] = Field(default_factory=dict)

    class LLMSettings(BaseSettings):
        llm: LLM = Field(default_factory=lambda: LLM())

        model_config = SettingsConfigDict(env_prefix='my_prefix_', env_nested_delimiter='__')

    env.set('my_prefix_llm__embeddings__openai__keys', '["sk-..."]')
    env.set('my_prefix_llm__embeddings__qwen__keys', '["sk-..."]')
    llm_setting = LLMSettings()
    assert llm_setting.llm.embeddings['openai'].keys == ['sk-...']
    assert llm_setting.llm.embeddings['qwen'].keys == ['sk-...']
