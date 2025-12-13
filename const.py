from base64 import b64encode
from uuid import uuid4
from json import dumps as stringify
from pathlib import Path
import re

dump_json = lambda d: stringify(d).encode()
base64_encode = lambda buf: b64encode(buf).decode()
def load_token():
    p = Path(".env")
    if p.exists() and (token := re.search(r"TOKEN=(.+)", p.read_text())):
        return token.group()
    return ""

TOKEN = load_token()
CLIENT_LAUNCH_ID = str(uuid4())
LAUNCH_SIGNATURE = str(uuid4())
CLIENT_HEARTBEAT_SESSION_ID = str(uuid4())
USERAGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.78 Chrome/118.0.5993.159 Electron/26.2.1 Safari/537.36"
SUPER_PROPERTIES = {
    "os": "Linux",
    "browser": "Discord Client",
    "release_channel": "stable",
    "client_version": "0.0.118",
    "os_version": "6.12.58-1-lts",
    "os_arch": "x64",
    "app_arch": "x64",
    "system_locale": "en-US",
    "has_client_mods": False,
    "client_launch_id": CLIENT_LAUNCH_ID,
    "browser_user_agent": USERAGENT,
    "browser_version": "37.6.0",
    "window_manager": "KDE,unknown",
    "distro": "Arch Linux",
    "runtime_environment": "native",
    "display_server": "wayland",
    "client_build_number": 479793,
    "native_build_number": None,
    "client_event_source": None,
    "launch_signature": LAUNCH_SIGNATURE,
    "client_heartbeat_session_id": CLIENT_HEARTBEAT_SESSION_ID,
    "client_app_state": "focused",
}

HEADERS = {
    "Referrer": "https://discord.com/quest-home",
    "Authorization": TOKEN,
    "User-Agent": USERAGENT,
    "X-Discord-Locale": "all",
    "X-Super-Properties": base64_encode(dump_json(SUPER_PROPERTIES)),
}
