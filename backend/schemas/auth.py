"""Auth API 요청·응답 형식."""

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: str
    must_change_password: bool = False   # True면 새 비밀번호를 정하기 전까지 다른 화면을 쓰지 못함


class StaffOut(UserOut):
    """배정·넘기기 상대 목록: 지금 맡은 미처리·긴급 건수와 담당 유형을 함께 (고르기 쉽게)"""
    open_count: int = 0
    urgent_open: int = 0
    categories: list[str] | None = None


class LoginResponse(BaseModel):
    user: UserOut
