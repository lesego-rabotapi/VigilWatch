"""Typed API errors.

Raise one from anywhere in a handler and `common.api.api_handler` turns it into a response.
Each class fixes the HTTP status and the machine-readable `code` clients can rely on, so a
message can be reworded without breaking anyone.
"""


class AppError(Exception):
    status = 500
    code = "internal_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ValidationError(AppError):
    status = 400
    code = "validation_error"


class UnauthorizedError(AppError):
    status = 401
    code = "unauthorized"


class NotFoundError(AppError):
    status = 404
    code = "not_found"


class LimitError(AppError):
    status = 429
    code = "limit_reached"
