from datetime import timedelta, timezone, datetime


def time_diff_now(utc_iso: str) -> timedelta:
    return time_diff(time_curr().isoformat(), utc_iso)


def time_diff(utc_iso_a: str, utc_iso_b: str) -> timedelta:
    return datetime.fromisoformat(utc_iso_a) - datetime.fromisoformat(utc_iso_b)


def time_in_past(utc_iso: str) -> bool:
    return time_curr() > datetime.fromisoformat(utc_iso)


def time_curr() -> datetime:
    return datetime.now(timezone.utc)
