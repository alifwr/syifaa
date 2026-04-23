from uuid import UUID
from pydantic import BaseModel, EmailStr, Field


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: UUID
    email: EmailStr


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshIn(BaseModel):
    refresh_token: str
