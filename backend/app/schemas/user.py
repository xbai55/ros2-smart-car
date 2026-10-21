from typing import Optional

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    display_name: str = ""
    email: Optional[str] = None
    role_names: list[str] = Field(default_factory=list)
    active: bool = True


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    role_names: Optional[list[str]] = None
    active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=128)


class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    description: str = ""
    permission_names: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    description: Optional[str] = None
    permission_names: Optional[list[str]] = None
