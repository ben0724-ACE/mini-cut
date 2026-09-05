"""Expected failures that are safe to present to MiniCut users."""


class MiniCutError(Exception):
    """Base class for expected failures with user-safe messages."""


class UserInputError(MiniCutError):
    """Raised when user-provided input cannot be accepted."""


class ProcessingError(MiniCutError):
    """Raised when an expected processing operation cannot complete."""


__all__ = ["MiniCutError", "ProcessingError", "UserInputError"]
