from pathlib import Path
from helpers import gen_id, load_token, dump_json, base64_encode

TOKEN = load_token()
CLIENT_LAUNCH_ID = gen_id()
LAUNCH_SIGNATURE = gen_id()
CLIENT_HEARTBEAT_SESSION_ID = gen_id()
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

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_PATH = Path("./logs/")

LOG_PATH.mkdir(exist_ok=True)
