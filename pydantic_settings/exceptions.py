class SettingsError(ValueError):
    """Base exception for settings-related errors."""

    pass


class IncompleteFieldDefinitionWarning(UserWarning):
    """Warning emitted when a field with an incomplete definition is used during settings resolution.

    A field definition is incomplete when its annotation contains unresolved forward references,
    in which case settings sources may fail to correctly resolve its value.
    """

    pass
