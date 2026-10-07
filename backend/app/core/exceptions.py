"""
Excepciones personalizadas del dominio y handlers para FastAPI.

Todas las respuestas de error siguen el formato:
{
    "detail": {
        "code": "CÓDIGO_UNICO",
        "message": "Mensaje legible en español",
        "extra": { ... datos opcionales ... }
    }
}
"""

from __future__ import annotations

from typing import Any, Dict

# ============================================================
# BASE
# ============================================================


class AppException(Exception):
    """Excepción base de la aplicación."""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str,
        code: str | None = None,
        extra: Dict[str, Any] | None = None,
    ):
        self.message = message
        if code:
            self.code = code
        self.extra = extra or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        detail: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.extra:
            detail["extra"] = self.extra
        return {"detail": detail}


# ============================================================
# 400 - BAD REQUEST
# ============================================================


class BadRequest(AppException):
    status_code = 400
    code = "BAD_REQUEST"


class ValidationError(BadRequest):
    """Error de validación de datos de entrada."""

    code = "VALIDATION_ERROR"

    def __init__(self, message: str = "Datos de entrada inválidos", field_errors: list | None = None):
        super().__init__(message, extra={"field_errors": field_errors or []})


class PasswordPolicyError(BadRequest):
    code = "PASSWORD_POLICY_ERROR"

    def __init__(self, errors: list):
        super().__init__("La contraseña no cumple la política", extra={"errors": errors})


# ============================================================
# 401 - UNAUTHORIZED
# ============================================================


class Unauthorized(AppException):
    status_code = 401
    code = "UNAUTHORIZED"


class InvalidCredentials(Unauthorized):
    code = "INVALID_CREDENTIALS"

    def __init__(self, message: str = "Credenciales inválidas"):
        super().__init__(message)


class TokenExpired(Unauthorized):
    code = "TOKEN_EXPIRED"

    def __init__(self, message: str = "Token expirado. Renueve su sesión."):
        super().__init__(message)


class TokenInvalid(Unauthorized):
    code = "TOKEN_INVALID"

    def __init__(self, message: str = "Token inválido"):
        super().__init__(message)


class AccountLocked(Unauthorized):
    code = "ACCOUNT_LOCKED"

    def __init__(self, minutes: int = 30):
        super().__init__(
            f"Cuenta bloqueada por intentos fallidos. Intente en {minutes} minutos.",
            extra={"lockout_minutes": minutes},
        )


class TOTPInvalid(Unauthorized):
    code = "TOTP_INVALID"

    def __init__(self, message: str = "Código de verificación incorrecto"):
        super().__init__(message)


# ============================================================
# 403 - FORBIDDEN
# ============================================================


class Forbidden(AppException):
    status_code = 403
    code = "FORBIDDEN"


class PermissionDenied(Forbidden):
    code = "PERMISSION_DENIED"

    def __init__(self, action: str = "realizar esta operación"):
        super().__init__(f"No tiene permiso para {action}")


class SeparationOfDutiesError(Forbidden):
    """Separación de funciones: no puede aprobar su propio trabajo."""

    code = "SEPARATION_OF_DUTIES"

    def __init__(self, message: str = "No puede aprobar su propio trabajo (separación de funciones)"):
        super().__init__(message)


class EmployeeInactive(Forbidden):
    code = "EMPLOYEE_INACTIVE"

    def __init__(self, message: str = "El empleado no está activo y no puede recibir nuevas tareas"):
        super().__init__(message)


# ============================================================
# 404 - NOT FOUND
# ============================================================


class NotFound(AppException):
    status_code = 404
    code = "NOT_FOUND"

    def __init__(self, entity: str = "Registro", identifier: Any = None):
        msg = f"{entity} no encontrado"
        extra = {}
        if identifier is not None:
            msg = f"{entity} con identificador '{identifier}' no encontrado"
            extra = {"identifier": str(identifier)}
        super().__init__(msg, extra=extra)


# ============================================================
# 409 - CONFLICT
# ============================================================


class Conflict(AppException):
    status_code = 409
    code = "CONFLICT"


class DuplicateValue(Conflict):
    code = "DUPLICATE_VALUE"

    def __init__(self, field: str, value: str):
        super().__init__(
            f"El valor '{value}' ya existe en el campo '{field}'",
            extra={"field": field, "value": value},
        )


class InvalidStateTransition(Conflict):
    """Transición de estado no válida."""

    code = "INVALID_STATE_TRANSITION"

    def __init__(self, entity: str, current: str, target: str, allowed: list | None = None):
        msg = f"Transición de estado inválida en {entity}: '{current}' → '{target}'"
        extra: Dict[str, Any] = {"current_state": current, "target_state": target}
        if allowed:
            extra["allowed_states"] = allowed
            msg += f". Estados permitidos: {', '.join(allowed)}"
        super().__init__(msg, extra=extra)


class HasHistoryError(Conflict):
    """No se puede eliminar registro con historial."""

    code = "HAS_HISTORY"

    def __init__(self, entity: str, message: str | None = None):
        msg = (
            message
            or f"No se puede eliminar {entity}: tiene historial asociado. Use el estado 'Dado de baja' o 'Anulado'."
        )
        super().__init__(msg)


# ============================================================
# 422 - UNPROCESSABLE (reglas de negocio)
# ============================================================


class BusinessRuleError(AppException):
    """Violación de regla de negocio."""

    status_code = 422
    code = "BUSINESS_RULE_ERROR"

    def __init__(self, message: str, rule: str | None = None):
        extra = {}
        if rule:
            extra = {"rule": rule}
        super().__init__(message, extra=extra)


class CylinderNotAptoForLlenado(BusinessRuleError):
    def __init__(self, estado: str):
        super().__init__(
            f"El cilindro no puede enviarse a llenado: estado actual '{estado}'",
            rule="RN09",
        )


class HydraulicTestExpired(BusinessRuleError):
    def __init__(self, vencimiento):
        super().__init__(
            f"Prueba hidráulica vencida desde {vencimiento}",
            rule="RN10",
        )


class CylinderNotApprovedForDelivery(BusinessRuleError):
    def __init__(self, estado: str):
        super().__init__(
            f"El cilindro no puede entregarse: estado '{estado}' (requiere APROBADO o LISTO_PARA_ENTREGAR)",
            rule="RN13",
        )


class OrderHasPendingTasks(BusinessRuleError):
    def __init__(self, pending_count: int):
        super().__init__(
            f"La orden tiene {pending_count} tarea(s) pendiente(s). No se puede cerrar.",
            rule="RN14",
        )


class DocumentRequiredForValorizedDelivery(BusinessRuleError):
    def __init__(self):
        super().__init__(
            "La entrega valorizada requiere un documento comercial asociado. "
            "Registre el documento o solicite autorización de excepción a un supervisor.",
            rule="RN34",
        )


class DocumentDuplicate(BusinessRuleError):
    def __init__(self, tipo: str, folio: str, emisor: str):
        super().__init__(
            f"Documento duplicado: tipo '{tipo}', folio '{folio}' para emisor '{emisor}' ya existe",
            rule="RN38",
        )


class DocumentAmountMismatch(BusinessRuleError):
    def __init__(self, doc_total, val_total, tolerance):
        super().__init__(
            f"El total del documento ({doc_total}) no coincide con la valorización ({val_total}). "
            f"Tolerancia: {tolerance}. Registre una justificación.",
            rule="RN39",
        )


class PriceHistoryImmutable(BusinessRuleError):
    def __init__(self):
        super().__init__(
            "No se puede modificar el precio histórico de una valorización existente",
            rule="RN31",
        )


# ============================================================
# 500 - INTERNAL
# ============================================================


class InternalError(AppException):
    status_code = 500
    code = "INTERNAL_ERROR"


class DatabaseError(InternalError):
    code = "DATABASE_ERROR"


class ExternalServiceError(InternalError):
    code = "EXTERNAL_SERVICE_ERROR"

    def __init__(self, service: str, message: str = ""):
        msg = f"Error en servicio externo '{service}'"
        if message:
            msg += f": {message}"
        super().__init__(msg, extra={"service": service})
