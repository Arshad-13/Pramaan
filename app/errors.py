"""Service-layer errors that map to HTTP responses.

Services raise these; one exception handler (registered in main.py) turns them into JSON. Messages
are deliberately generic where detail would help an attacker (no user enumeration).
"""

from __future__ import annotations


class ServiceError(Exception):
    status_code = 400
    detail = "Bad request"

    def __init__(self, detail: str | None = None, extra: dict | None = None) -> None:
        super().__init__(detail or self.detail)
        self.message = detail or self.detail
        self.extra = extra or {}  # additional JSON fields for the response body
        self.headers: dict[str, str] = {}  # additional response headers


class AuthFailed(ServiceError):
    """Wrong credentials, unknown account, locked account: all look identical to the caller."""

    status_code = 401
    detail = "Invalid email or password."


class NotAuthenticated(ServiceError):
    status_code = 401
    detail = "Not authenticated."


class Forbidden(ServiceError):
    status_code = 403
    detail = "You do not have permission to do that."


class AccountNotUsable(ServiceError):
    """Credentials were right, but the account cannot be used (pending, rejected, disabled)."""

    status_code = 403
    detail = "This account cannot sign in right now."


class NotFound(ServiceError):
    status_code = 404
    detail = "Not found."


class Conflict(ServiceError):
    status_code = 409
    detail = "That already exists."


class BadRequest(ServiceError):
    status_code = 400
    detail = "Bad request."


class Locked(ServiceError):
    """A resource is temporarily locked (for example the signing key after wrong passwords)."""

    status_code = 423
    detail = "Temporarily locked."


class RiskConfirmationRequired(ServiceError):
    """The prescription looks unusual: the doctor must confirm with a reason before it is signed."""

    status_code = 409
    detail = "This prescription needs your confirmation before it can be signed."


class PayloadTooLarge(ServiceError):
    status_code = 413
    detail = "The file is too large."


class ServiceBusy(ServiceError):
    status_code = 503
    detail = "The checker is busy. Try again in a few seconds."


class TooManyRequests(ServiceError):
    status_code = 429
    detail = "Too many attempts. Wait a moment and try again."

    def __init__(self, retry_after: int = 60) -> None:
        super().__init__()
        self.headers["Retry-After"] = str(retry_after)
        self.extra = {"retry_after": retry_after}
