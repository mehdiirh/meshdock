"""Typed adapter settings and shared rules consumed by both API and UI."""

import json
from typing import ClassVar, Literal, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def option(default, *, scope="both", unit=None, when=None, **limits):
    metadata = {"scope": scope}
    if unit:
        metadata["unit"] = unit
    if when:
        metadata["when"] = when
    return Field(default=default, json_schema_extra=metadata, **limits)


def active(metadata, values):
    return all(values.get(key) in allowed for key, allowed in metadata.get("when", {}).items())


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)
    rules: ClassVar[list[dict]] = []

    @field_validator("*", mode="before")
    @classmethod
    def strict_choices(cls, value, info):
        annotation = cls.model_fields[info.field_name].annotation
        if get_origin(annotation) is Literal and not any(
            type(value) is type(choice) and value == choice for choice in get_args(annotation)
        ):
            raise ValueError("invalid_choice")
        return value

    @classmethod
    def schema(cls):
        schema = cls.model_json_schema()
        schema["rules"] = cls.rules
        schema["version"] = 1
        return schema

    @model_validator(mode="after")
    def compatible(self):
        values = self.model_dump()
        for name in self.model_fields_set:
            metadata = type(self).model_fields[name].json_schema_extra or {}
            if not active(metadata, values):
                raise ValueError("inactive_option")
        for rule in self.rules:
            if active(rule, values):
                left, right = values[rule["left"]], values[rule["right"]]
                if left > right or (rule["operator"] == "lt" and left == right):
                    raise ValueError("incompatible_options")
        return self

    def values(self, scope=None):
        values = self.model_dump()
        return {
            key: value
            for key, value in values.items()
            if active(type(self).model_fields[key].json_schema_extra or {}, values)
            and (
                scope is None
                or (type(self).model_fields[key].json_schema_extra or {}).get("scope")
                in ("both", scope)
            )
        }


def toml_values(values):
    """Settings contain only validated scalars; JSON quoting is valid TOML here."""
    return "".join(f"{key} = {json.dumps(value)}\n" for key, value in values.items())
