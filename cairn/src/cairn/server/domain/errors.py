from __future__ import annotations


class DomainError(Exception):
    """Business-rule failure raised below the HTTP layer."""

    status_code: int = 500

    def __init__(self, detail: str, *, status_code: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code


class BadRequestError(DomainError):
    status_code = 400


class NotFoundError(DomainError):
    status_code = 404


class ForbiddenError(DomainError):
    status_code = 403


class ConflictError(DomainError):
    status_code = 409


class ServerInvariantError(DomainError):
    status_code = 500
