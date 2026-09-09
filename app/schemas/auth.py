from pydantic import BaseModel


class TeamLoginRequest(BaseModel):
    team_code: str
    password: str


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
