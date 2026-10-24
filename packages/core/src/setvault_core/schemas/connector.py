from __future__ import annotations

from typing import Annotated, Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator, BaseModel, Field, model_validator


def _validate_email_permissive(value: str) -> str:
    """Validate an email but allow reserved TLDs (e.g. .test, .example) used in tests."""
    try:
        result = validate_email(value, check_deliverability=False, test_environment=True)
    except EmailNotValidError as exc:
        raise ValueError(str(exc)) from exc
    return result.normalized


PermissiveEmail = Annotated[str, AfterValidator(_validate_email_permissive)]


class SmtpConfigIn(BaseModel):
    host: str
    port: int = Field(ge=1, le=65535)
    encryption: Literal["starttls", "ssl", "none"]
    username: str | None = None
    password: str | None = None
    from_email: PermissiveEmail
    from_name: str
    reply_to: PermissiveEmail | None = None


class SmtpConfigPatchIn(BaseModel):
    """Partial SMTP config. Absent fields keep their stored value.

    ``username``/``reply_to`` accept an explicit null to clear them. A
    ``password`` that is absent or ``""`` keeps the stored one; null clears it.
    """

    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    encryption: Literal["starttls", "ssl", "none"] | None = None
    username: str | None = None
    password: str | None = None
    from_email: PermissiveEmail | None = None
    from_name: str | None = None
    reply_to: PermissiveEmail | None = None

    @model_validator(mode="after")
    def _required_fields_not_null(self) -> SmtpConfigPatchIn:
        for name in ("host", "port", "encryption", "from_email", "from_name"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class SmtpConfigOut(BaseModel):
    host: str
    port: int
    encryption: Literal["starttls", "ssl", "none"]
    username: str | None
    password_set: bool
    from_email: str
    from_name: str
    reply_to: str | None


class ConnectorCreateIn(BaseModel):
    kind: Literal["smtp"]
    name: str
    config: SmtpConfigIn
    scope_filter: dict = Field(default_factory=lambda: {"kinds": ["*"]})
    enabled: bool = True


class ConnectorPatchIn(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    config: SmtpConfigPatchIn | None = None

    @model_validator(mode="after")
    def _no_null_name_or_enabled(self) -> ConnectorPatchIn:
        for name in ("name", "enabled", "config"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class ConnectorOut(BaseModel):
    id: str
    kind: str
    name: str
    enabled: bool
    scope_filter: dict
    config: SmtpConfigOut


class TestSendIn(BaseModel):
    to: PermissiveEmail
    dry_run: bool = False


class TestSendOut(BaseModel):
    accepted: bool
    dry_run: bool
    error: str | None = None
