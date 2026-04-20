from typing import Optional

from pydantic import BaseModel, Field


class SignupRequest(BaseModel):
	username: str = Field(..., min_length=3, max_length=255, examples=["newuser"])
	email: str = Field(..., min_length=5, max_length=255, examples=["newuser@example.com"])
	password: str = Field(..., min_length=8, examples=["ChangeMe123!"])


class LoginRequest(BaseModel):
	username: str = Field(..., min_length=3, examples=["admin"])
	password: str = Field(..., min_length=8, examples=["ChangeMe123!"])


class RefreshRequest(BaseModel):
	refresh_token: str = Field(..., min_length=20)


class LogoutRequest(BaseModel):
	access_token: str = Field(..., min_length=20)
	refresh_token: Optional[str] = None


class VerifyRequest(BaseModel):
	access_token: str = Field(..., min_length=20)


class MeRequest(BaseModel):
	access_token: str = Field(..., min_length=20)


class TokenResponse(BaseModel):
	access_token: str
	refresh_token: str
	token_type: str = "bearer"
	expires_in: int


class VerifyResponse(BaseModel):
	user_id: str
	username: str
	jti: str
	exp: int


class MeResponse(BaseModel):
	user_id: str
	username: str
	email: str
