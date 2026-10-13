"""Validated public contracts. Remote shell/config values are deliberately narrow."""

import re
from ipaddress import IPv4Address
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Revision(Model):
    revision: int = Field(ge=0)


class Login(Model):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)


class Password(Model):
    current: str = Field(max_length=1024)
    password: str = Field(min_length=12, max_length=1024)


class Credential(Model):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["password", "key"]
    secret: str = Field(min_length=1, max_length=32768)
    passphrase: str = Field(default="", max_length=1024)


class Position(Model):
    x: float = Field(ge=-100000, le=100000, allow_inf_nan=False)
    y: float = Field(ge=-100000, le=100000, allow_inf_nan=False)


class Host(Model):
    host: str = Field(min_length=1, max_length=253)
    ssh_port: int = Field(default=22, ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def hostname(cls, v):
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", v):
            raise ValueError("hostname")
        return v.lower()


class Server(Host):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    name: str = Field(min_length=1, max_length=80)
    role: Literal["entry", "exit", "both"]
    address: str
    credential_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    fingerprint: str = Field(pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")
    region: str = Field(default="", max_length=80)
    position: Position

    @field_validator("address")
    @classmethod
    def ipv4(cls, v):
        return str(IPv4Address(v))


class Port(Model):
    public: int = Field(ge=1, le=65535)
    target: int = Field(ge=1, le=65535)
    host: str = "127.0.0.1"

    @field_validator("host")
    @classmethod
    def target_ip(cls, v):
        return str(IPv4Address(v))


class Link(Model):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    entry_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    exit_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    method: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    enabled: bool = True
    ports: list[Port] = Field(min_length=1, max_length=16)
    policy: Literal["roundrobin", "leastconn", "failover"] = "roundrobin"
    weight: int = Field(default=1, ge=1, le=256)


class Topology(Revision):
    servers: list[Server] = Field(max_length=500)
    links: list[Link] = Field(max_length=1000)


class Positions(Model):
    positions: dict[str, Position] = Field(max_length=500)


class ApiKey(Model):
    name: str = Field(min_length=1, max_length=80)
    scope: Literal["read", "write", "admin"] = "read"
