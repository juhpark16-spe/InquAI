"""계정 관리 API(관리자) 요청·응답 형식."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.core.config import get_settings
from backend.schemas.common import UTCDateTime
from backend.training.labels import CATEGORY_LABELS

USERNAME_PATTERN = r"^[a-z0-9_]{3,30}$"  # 영문 소문자·숫자·밑줄 3~30자

Category = Literal[tuple(CATEGORY_LABELS)]


def _unique_in_order(v: list[str]) -> list[str]:
    """중복을 없애고 유형 순서(labels.py)대로 정렬"""
    return [c for c in CATEGORY_LABELS if c in set(v)]


class UserDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: str
    categories: list[str]  # 빈 목록 = 전체 담당
    is_active: bool
    locked_until: UTCDateTime | None
    last_login_at: UTCDateTime | None
    created_at: UTCDateTime
    must_change_password: bool = False   # 임시 비밀번호 상태 (본인이 아직 바꾸지 않음)

    @field_validator("categories", mode="before")
    @classmethod
    def _none_to_list(cls, v):
        return v or []


def check_password_length(v: str) -> str:
    """최소 길이는 설정값(PASSWORD_MIN_LENGTH, 기본 8)을 따름. 시연 환경에서만 낮춰 씀"""
    n = get_settings().password_min_length
    if len(v) < n:
        raise ValueError(f"비밀번호는 {n}자 이상이어야 합니다.")
    return v


class _Password(BaseModel):
    password: str = Field(min_length=1, max_length=128)

    @field_validator("password")
    @classmethod
    def _length(cls, v):
        return check_password_length(v)


class PasswordChange(BaseModel):
    """본인 비밀번호 변경 (POST /api/auth/change-password)"""
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _length(cls, v):
        return check_password_length(v)


class UserCreate(_Password):
    username: str = Field(pattern=USERNAME_PATTERN)
    display_name: str = Field(min_length=1, max_length=50)
    role: Literal["admin", "agent"] = "agent"
    categories: list[Category] = Field(default_factory=list, description="담당 유형. 비우면 전체 담당")

    @field_validator("username", "display_name", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("categories")
    @classmethod
    def _order(cls, v):
        return _unique_in_order(v)


class UserUpdate(BaseModel):
    """바꿀 항목만 보냅니다."""
    display_name: str | None = Field(default=None, min_length=1, max_length=50)
    role: Literal["admin", "agent"] | None = None
    is_active: bool | None = None
    categories: list[Category] | None = None

    @field_validator("categories")
    @classmethod
    def _order(cls, v):
        return None if v is None else _unique_in_order(v)


class PasswordReset(_Password):
    pass
