from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class OptionType(Enum):
    String = "str"
    Integer = "int"
    Float = "float"
    Boolean = "bool"
    DiscordChannel = "channel"

    def validate(self, raw: str) -> Any:
        """Validate and convert a string value to the target type."""
        match self:
            case OptionType.String:
                return raw
            case OptionType.Integer:
                try:
                    return int(raw)
                except ValueError:
                    raise ValueError(f"`{raw}` is not a valid integer")
            case OptionType.Float:
                try:
                    return float(raw)
                except ValueError:
                    raise ValueError(f"`{raw}` is not a valid number")
            case OptionType.Boolean:
                if raw.lower() in ("yes", "true", "1"):
                    return True
                if raw.lower() in ("no", "false", "0"):
                    return False
                raise ValueError(f"invalid boolean value: {raw!r}")
            case OptionType.DiscordChannel:
                try:
                    channel_id = int(raw.strip("<#>"))
                except ValueError:
                    raise ValueError(f"`{raw}` is not a valid channel ID")
                return channel_id

    def humanize(self, value: Any) -> str | None:
        """Convert a value to human-readable string for display."""
        if value is None:
            return None
        match self:
            case OptionType.Boolean:
                return "✅" if value else "❌"
            case OptionType.DiscordChannel:
                return f"<#{value}>"
            case _:
                return str(value)

    def serialize(self, value: Any) -> Any:
        """Convert a value for JSON storage."""
        match self:
            case OptionType.Boolean:
                return bool(value)
            case OptionType.Integer | OptionType.DiscordChannel:
                return int(value)
            case OptionType.Float:
                return float(value)
            case _:
                return value

    def deserialize(self, raw: Any) -> Any:
        """Convert a JSON value back to Python type."""
        match self:
            case OptionType.Boolean:
                return bool(raw)
            case OptionType.Integer | OptionType.DiscordChannel:
                return int(raw)
            case OptionType.Float:
                return float(raw)
            case _:
                return raw

    @property
    def label(self) -> str:
        return self.value


@dataclass
class CommandOption:
    key: str
    description: str
    type: OptionType
    required: bool = True
    default: Any = None
    positional: bool = False

    def __post_init__(self) -> None:
        if self.default is not None:
            self.required = False


@dataclass
class ConfigOption:
    key: str
    description: str
    type: OptionType
    default: Any = None
