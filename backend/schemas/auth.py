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


class LoginResponse(BaseModel):
    user: UserOut
