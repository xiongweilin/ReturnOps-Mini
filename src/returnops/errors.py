from __future__ import annotations


class ReturnOpsError(RuntimeError):
    code = "returnops_error"
    status_code = 400

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AuthenticationError(ReturnOpsError):
    code = "unauthenticated"
    status_code = 401


class PermissionDenied(ReturnOpsError):
    code = "permission_denied"
    status_code = 403


class NotFound(ReturnOpsError):
    code = "not_found"
    status_code = 404


class Conflict(ReturnOpsError):
    code = "conflict"
    status_code = 409


class VersionConflict(Conflict):
    code = "version_conflict"


class IdempotencyConflict(Conflict):
    code = "idempotency_conflict"


class InvalidTransition(Conflict):
    code = "invalid_transition"


class ValidationFailure(ReturnOpsError):
    code = "validation_error"
    status_code = 422


class ExternalSystemFailure(ReturnOpsError):
    code = "external_system_failure"
    status_code = 502
