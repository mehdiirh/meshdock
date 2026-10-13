"""Persistence models. API contracts live in schemas.py; Alembic owns all DDL."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float)


class Session(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    csrf: Mapped[str] = mapped_column(String(128))
    expires: Mapped[float] = mapped_column(Float, index=True)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scope: Mapped[str] = mapped_column(String(16))
    created: Mapped[float] = mapped_column(Float)
    last_used: Mapped[float | None] = mapped_column(Float)
    revoked: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Credential(Base):
    __tablename__ = "credentials"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(16))
    encrypted: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float)


class Server(Base):
    __tablename__ = "servers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    host: Mapped[str] = mapped_column(String(253))
    ssh_port: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    address: Mapped[str] = mapped_column(String(45))
    credential_id: Mapped[str] = mapped_column(ForeignKey("credentials.id"))
    fingerprint: Mapped[str] = mapped_column(String(128))
    region: Mapped[str] = mapped_column(String(80))
    position: Mapped[str] = mapped_column(Text)
    deleted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created: Mapped[float] = mapped_column(Float)


class Link(Base):
    __tablename__ = "links"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    entry_id: Mapped[str] = mapped_column(ForeignKey("servers.id"))
    exit_id: Mapped[str] = mapped_column(ForeignKey("servers.id"))
    method: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[int] = mapped_column(Integer)
    ports: Mapped[str] = mapped_column(Text)
    policy: Mapped[str] = mapped_column(String(16))
    weight: Mapped[int] = mapped_column(Integer)
    slot: Mapped[int] = mapped_column(Integer, unique=True)
    encrypted: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float)


class State(Base):
    __tablename__ = "state"
    __table_args__ = (CheckConstraint("id=1"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    namespace: Mapped[str] = mapped_column(String(10))
    revision: Mapped[int] = mapped_column(Integer)
    applied_revision: Mapped[int] = mapped_column(Integer)
    applied: Mapped[str] = mapped_column(Text)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("jobs_queue", "status", "next_run", "created"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    snapshot: Mapped[str] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created: Mapped[float] = mapped_column(Float)
    started: Mapped[float | None] = mapped_column(Float)
    finished: Mapped[float | None] = mapped_column(Float)
    next_run: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    lease_until: Mapped[float | None] = mapped_column(Float)
    owner: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64))
    receipt: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")


class Log(Base):
    __tablename__ = "logs"
    __table_args__ = (Index("logs_job", "job_id", "id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    server_id: Mapped[str | None] = mapped_column(String(32))
    level: Mapped[str] = mapped_column(String(16))
    code: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float)


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, index=True)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    bucket: Mapped[str] = mapped_column(String(80), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    until: Mapped[float] = mapped_column(Float)


class Leader(Base):
    __tablename__ = "leader"
    __table_args__ = (CheckConstraint("id=1"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(32))
    until: Mapped[float] = mapped_column(Float)
