"""계정 관리 API(관리자) 요청·응답 형식."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.schemas.common import UTCDateTime
from backend.training.labels import CATEGORY_LABELS

USERNAME_PATTERN = r"^[a-z0-9_]{3,30}$"  # 영문 소문자·숫자·밑줄 3~30자
PASSWORD_MIN = 8

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

    @field_validator("categories", mode="before")
    @classmethod
    def _none_to_list(cls, v):
        return v or []


class _Password(BaseModel):
    password: str = Field(min_length=PASSWORD_MIN, max_length=128)


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
