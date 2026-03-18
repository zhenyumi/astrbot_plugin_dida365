from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE_NAME = "Asia/Shanghai"


def resolve_timezone_name(
    preferred_timezone: str = "",
    *,
    fallback_timezone: str = DEFAULT_TIMEZONE_NAME,
) -> str:
    candidate = str(preferred_timezone or "").strip()
    fallback = str(fallback_timezone or "").strip() or DEFAULT_TIMEZONE_NAME

    if candidate:
        try:
            ZoneInfo(candidate)
            return candidate
        except ZoneInfoNotFoundError:
            pass

    try:
        ZoneInfo(fallback)
        return fallback
    except ZoneInfoNotFoundError:
        return DEFAULT_TIMEZONE_NAME


def get_timezone(timezone_name: str):
    resolved_name = resolve_timezone_name(timezone_name)
    try:
        return ZoneInfo(resolved_name)
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone().tzinfo


def now_in_timezone(timezone_name: str) -> datetime:
    return datetime.now(get_timezone(timezone_name))


def today_in_timezone(timezone_name: str) -> date:
    return now_in_timezone(timezone_name).date()


def parse_api_datetime(
    value: str,
    *,
    assume_timezone_name: str,
    target_timezone_name: str,
) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    normalized = text.replace("Z", "+00:00")
    if len(normalized) >= 5 and normalized[-5] in {"+", "-"} and normalized[-3] != ":":
        normalized = f"{normalized[:-2]}:{normalized[-2:]}"

    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        date_part = text[:10]
        try:
            parsed = datetime.fromisoformat(date_part)
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=get_timezone(assume_timezone_name))

    return parsed.astimezone(get_timezone(target_timezone_name))
