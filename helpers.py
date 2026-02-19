from typing import Iterator, Iterable
from base64 import b64encode
from json import dumps
from logging import DEBUG, Formatter, Logger
from logging.handlers import RotatingFileHandler
from os import getenv
from pathlib import Path
from uuid import uuid4
import re


def dump_json(data: object):
    return dumps(data).encode()


def base64_encode(buf):
    return b64encode(buf).decode()


def gen_id():
    return str(uuid4())


def load_token():
    if token_env := getenv("token", getenv("TOKEN")):
        return token_env

    p = Path(".env")
    if p.exists() and (token := re.search(r"TOKEN=(.+)", p.read_text())):
        return token.group(1)

    return ""


def normalize(obj):
    if isinstance(obj, Iterator):
        return list(obj)
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [normalize(x) for x in obj]
    return obj


def save_data(data: dict | Iterable, path: Path) -> Path:
    path = Path(path).with_suffix(".json")
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(dumps(normalize(data), indent=2, ensure_ascii=False))
    tmp.replace(path)

    return path


def get_logger(
    name: str,
    log_path: Path,
    log_format: str,
    date_format: str,
):
    handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(Formatter(log_format, date_format))

    logger = Logger(name, DEBUG)
    logger.addHandler(handler)

    return logger
