# src/auth/domain/schemas.py
"""
Pydantic schemas for authentication.
"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from src.shared.domain.locale import DEFAULT_COUNTRY, default_locale, default_timezone, validate_timezone

from .models import BCRYPT_MAX_PASSWORD_BYTES


def _bcrypt_sized(password: str) -> str:
    if len(password.encode()) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(f"La contraseña puede tener como máximo {BCRYPT_MAX_PASSWORD_BYTES} bytes.")
    return password


# New passwords: at least 8 characters, at most what bcrypt actually hashes (72 bytes).
NewPassword = Annotated[str, Field(min_length=8), AfterValidator(_bcrypt_sized)]


class UserBase(BaseModel):
    """Base user schema."""
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    # Where the person is: sets the agent's voice and local time. Timezone/locale default from the country.
    country: Literal["AR", "MX"] = DEFAULT_COUNTRY
    timezone: str | None = None
    locale: str | None = Field(default=None, pattern=r"^[a-z]{2}-[A-Z]{2}$")

    @field_validator("timezone")
    @classmethod
    def _iana_timezone(cls, value: str | None) -> str | None:
        return validate_timezone(value) if value else value


class SignupRequest(UserBase):
    """Creates a new account and its owner user."""
    password: NewPassword
    account_name: str | None = Field(default=None, max_length=255)


class MemberCreate(UserBase):
    """An account owner adds a family member / technician to the account."""
    password: NewPassword
    role: Literal["tecnico", "staff"] = "staff"


class UserLocaleUpdate(BaseModel):
    """`PATCH /auth/me`: change where I am. Omitted fields stay as they are; changing the country alone resets the
    timezone and locale to that country's defaults unless they are sent too."""
    country: Literal["AR", "MX"] | None = None
    timezone: str | None = None
    locale: str | None = Field(default=None, pattern=r"^[a-z]{2}-[A-Z]{2}$")

    @field_validator("timezone")
    @classmethod
    def _iana_timezone(cls, value: str | None) -> str | None:
        return validate_timezone(value) if value else value


class MemberRoleUpdate(BaseModel):
    role: Literal["tecnico", "staff"]


class UserCreate(UserBase):
    """Internal DTO for creating a user."""
    password: str
    account_id: UUID
    role: str

    @model_validator(mode="after")
    def _fill_locale_defaults(self):
        self.timezone = self.timezone or default_timezone(self.country)
        self.locale = self.locale or default_locale(self.country)
        return self


class UserRead(UserBase):
    """Schema for reading user data."""
    id: UUID
    account_id: UUID
    role: str | None = None
    is_enrolled: bool = False
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AccountRead(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MeResponse(BaseModel):
    user: UserRead
    account: AccountRead


class LoginRequest(BaseModel):
    """Schema for login request."""
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


class PasswordChangeRequest(BaseModel):
    """Schema for a self-service password change."""
    current_password: str = Field(max_length=1024)
    new_password: NewPassword


class TokenResponse(BaseModel):
    """Schema for token response."""
    access_token: str
    token_type: str = "bearer"


# ============================================
# User Profile / Enrollment Schemas
# ============================================

class EnrollRequest(BaseModel):
    """
    Formulario de onboarding con las 10 respuestas.
    
    Expected format:
    {
        "form": {
            "q1": "A",  # Experiencia - trayectoria
            "q2": "B",  # Experiencia - familiaridad técnica
            "q3": "C",  # Objetivo - destino de frutos
            "q4": "A",  # Riesgo - manejo de plagas
            "q5": "B",  # Riesgo - estrés de planta
            "q6": "A",  # Filosofía - agroquímicos
            "q7": "B",  # Filosofía - bio-insumos
            "q8": "C",  # Tecnología - comodidad con IA
            "q9": "B",  # Innovación - experimentación
            "q10": "A"  # Control - gestión de registros
        }
    }
    """
    form: dict


class UserProfileRead(BaseModel):
    """Schema for reading user profile data."""
    id: UUID
    user_id: UUID
    form: dict
    experience: str | None = None
    goal: str | None = None
    risk: str | None = None
    philosophy: str | None = None
    profile: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserProfileContext(BaseModel):
    """
    Contexto para el agente basado en el perfil del usuario.
    
    Este objeto se usa para configurar el comportamiento del agente
    según el perfil psicológico del productor.
    """
    calculated_profile: str  # "guardian", "purist", "alchemist", "professional"
    config: dict  # Configuración específica del agente
    
    model_config = ConfigDict(json_schema_extra={
            "example": {
                "calculated_profile": "alchemist",
                "config": {
                    "technical_tone": "high_scientific",
                    "risk_tolerance": "high_experimental",
                    "sanitary_framework": "integrated_management",
                    "priority": "quality_optimization",
                    "alert_threshold": "critical_only"
                }
            }
        })
