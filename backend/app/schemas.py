"""Validated public contracts. Remote shell/config values are deliberately narrow."""

import re
from ipaddress import IPv4Address
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ports import bounds, normalize, segments


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
    public: int | str
    target: int | str
    exclude: list[int | str] = Field(default_factory=list, max_length=128)

    @field_validator("public", "target", mode="before")
    @classmethod
    def port_range(cls, value):
        return normalize(value)

    @field_validator("exclude", mode="before")
    @classmethod
    def exceptions(cls, values):
        if not isinstance(values, list):
            raise ValueError("port_exclusions")
        return [normalize(value) for value in values]

    @model_validator(mode="after")
    def matching_ranges(self):
        first, last = bounds(self.public)
        target_first, target_last = bounds(self.target)
        if last - first != target_last - target_first:
            raise ValueError("range_width")
        previous = first - 1
        for start, end in sorted(bounds(value) for value in self.exclude):
            if start < first or end > last or start <= previous:
                raise ValueError("port_exclusions")
            previous = end
        if not list(segments(self.model_dump())):
            raise ValueError("empty_mapping")
        return self

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
    control_port: int | None = Field(default=None, ge=1, le=65535)
    ports: list[Port] = Field(min_length=1, max_length=16)
    policy: Literal["roundrobin", "leastconn", "failover"] = "roundrobin"
    weight: int = Field(default=1, ge=1, le=256)
    settings: dict[str, Any] = Field(default_factory=dict, max_length=64)


class Topology(Revision):
    servers: list[Server] = Field(max_length=500)
    links: list[Link] = Field(max_length=1000)


class Positions(Model):
    positions: dict[str, Position] = Field(max_length=500)


class ApiKey(Model):
    name: str = Field(min_length=1, max_length=80)
    scope: Literal["read", "write", "admin"] = "read"
