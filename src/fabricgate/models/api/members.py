"""Pydantic models for namespace member management."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MemberRole(StrEnum):
    """Member roles - aligned with API token scopes."""

    OWNER = "owner"
    ADMIN = "admin"
    WRITE = "write"
    READ = "read"


class NamespaceMemberResponse(BaseModel):
    """Response model for a single namespace member."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    username: str
    email: str | None = None
    role: MemberRole
    joined_at: datetime


class NamespaceMembersListResponse(BaseModel):
    """Response model for namespace members list."""

    members: list[NamespaceMemberResponse]
    total: int


class AddMemberRequest(BaseModel):
    """Request model to add a new member to a namespace."""

    username: str = Field(..., min_length=1, max_length=64)
    role: MemberRole = Field(...)


class UpdateMemberRoleRequest(BaseModel):
    """Request model to update a member's role."""

    role: MemberRole = Field(...)
