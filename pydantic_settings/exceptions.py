class SettingsError(ValueError):
    """Base exception for settings-related errors."""


class IncompleteFieldDefinitionWarning(UserWarning):
    """Warning emitted when a field with an incomplete definition is used during settings resolution.

    A field definition is incomplete when its annotation contains unresolved forward references,
    in which case settings sources may fail to correctly resolve its value.
    """


class IgnoredEnvKwargWarning(UserWarning):
    """Warning emitted when a field is declared with the pydantic v1 `env` keyword argument.

    `Field(env='VAR')` was the pydantic v1 spelling for binding a field to an environment
    variable. In pydantic v2 the keyword is stored in `json_schema_extra` and settings sources
    ignore it, so the field is not bound to `VAR`. Use `validation_alias` instead.
    """
