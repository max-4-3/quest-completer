from datetime import timedelta, timezone, datetime
import locale


def time_format(utc_iso: str, time: bool = False, sep: str = "@") -> str:
    fmt: str = "%Y-%m-%d"
    time_fmt: str | None = None
    try:
        fmt = locale.nl_langinfo(locale.D_FMT)
        if time:
            time_fmt = locale.nl_langinfo(locale.T_FMT)
    except (AttributeError, ValueError):
        if time:
            time_fmt = "%H:%M:%S"

    if time_fmt:
        fmt += f"{sep}{time_fmt}"

    return datetime.fromisoformat(utc_iso).strftime(fmt)


def time_parse(utc_iso: str) -> datetime:
    return datetime.fromisoformat(utc_iso or datetime.now().isoformat())


def time_diff_now(utc_iso: str) -> timedelta:
    return time_diff(time_curr().isoformat(), utc_iso)


def time_diff(utc_iso_a: str, utc_iso_b: str) -> timedelta:
    return datetime.fromisoformat(utc_iso_a) - datetime.fromisoformat(utc_iso_b)


def time_in_past(utc_iso: str) -> bool:
    return time_curr() > datetime.fromisoformat(utc_iso)


def time_curr() -> datetime:
    return datetime.now(timezone.utc)
