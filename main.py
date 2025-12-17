import asyncio
from collections import deque
from collections.abc import Iterable, Iterator
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import random
import re
from uuid import uuid4

import aiohttp
from pydotmap import DotMap
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
)
from rich.table import Table
from rich.text import Text

from const import HEADERS, SUPER_PROPERTIES, base64_encode, dump_json
from logic.quests import (
    Filters,
    complete_quest,
    determine_quest_type,
    enroll_quest,
    get_all_quests,
    get_progress,
    get_quest_name,
    get_rewards,
)

SPINNERS = [
    "dots",
    "line",
    "arc",
    "bounce",
    "moon",
    "earth",
    "clock",
    "hamburger",
    "pong",
    "shark",
    "weather",
]
LOG_FORMAT = (
    "%(asctime)s | " "%(levelname)-8s | " "%(name)s:%(lineno)d | " "%(message)s"
)

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

log_path = Path("./logs")
log_path.mkdir(parents=True, exist_ok=True)
handler = RotatingFileHandler(
    log_path / "completer.log",
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=3,
    encoding="utf-8",
)

handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))

logging.basicConfig(
    level=logging.DEBUG,
    handlers=[handler],
)
logger = logging.getLogger(__name__)


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

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(normalize(data), f, indent=2, ensure_ascii=False)

    tmp.replace(path)

    return path


def make_renderable(quest: DotMap, **text_kwargs):
    # Type, Name, Rewards, Progress
    def percentage(x, y) -> str:
        if not all(isinstance(i, (int, float)) for i in [x, y]):
            return "0.00%"
        return f"{(x / y if y else 0) * 100:.2f}%"

    return map(
        lambda x: Text(x, **text_kwargs),
        map(
            str,
            [
                determine_quest_type(quest).name,
                get_quest_name(quest).title(),
                ", ".join(map(lambda x: str(x).title(), get_rewards(quest))),
                percentage(*get_progress(quest)),
            ],
        ),
    )


def make_quests_table(quests: Iterable[DotMap], **table_kwargs) -> Table:
    table = Table(**table_kwargs, expand=True)

    list(map(table.add_column, ["#", "Type", "Name", "Rewards", "Progress"]))
    for idx, quest in enumerate(quests, 1):
        table.add_row(*[str(idx), *make_renderable(quest)])

    return table


def make_messages_panel(messages: Iterable):
    return Panel(
        Group(*messages),
        title="Messages",
        title_align="center",
        border_style="bold magenta",
        expand=True,
    )


def make_progress_panel(progress: Progress):
    return Panel(
        Group(progress),
        title="Progress",
        title_align="left",
        border_style="bold green",
        expand=True,
    )


def get_progress_columns():
    return (
        SpinnerColumn(random.choice(SPINNERS), finished_text="😋"),
        TextColumn(
            "{task.description}",
            style="italic cyan bold",
        ),
        BarColumn(None),
        MofNCompleteColumn(),
    )


def make_progress(console: Console):
    return Progress(
        *get_progress_columns(),
        console=console,
        expand=True,
    )


def make_layout(progress: Progress):
    layout = Layout()
    layout.split_column(
        Layout(name="messages", ratio=1), Layout(name="progress", size=3)
    )

    layout["messages"].update(make_messages_panel(["Initilizing..."]))
    layout["progress"].update(make_progress_panel(progress))

    return layout


async def change_heartbeat_id(session: aiohttp.ClientSession):
    while True:
        new_heartbeat_id = str(uuid4())
        SUPER_PROPERTIES["client_heartbeat_session"] = new_heartbeat_id
        session.headers.update(
            {"X-Super-Properties": base64_encode(dump_json(SUPER_PROPERTIES))}
        )
        logger.debug("Changed heartbeat session id")
        await asyncio.sleep(30 * 60)


async def update_headers(session: aiohttp.ClientSession):
    raw_html = await (await session.get("/")).text()
    build_number_match = re.search(r""""BUILD_NUMBER":\s*"(\d+)""", raw_html)
    if build_number_match:
        SUPER_PROPERTIES["client_build_number"] = int(build_number_match.group(1))
    HEADERS["X-Super-Properties"] = base64_encode(dump_json(SUPER_PROPERTIES))

    session.headers.update(HEADERS)


async def main():
    async with aiohttp.ClientSession(
        base_url="https://discord.com/api/v10/", raise_for_status=True
    ) as session:
        asyncio.create_task(change_heartbeat_id(session))
        await update_headers(session)
        console = Console()
        progress = make_progress(console)
        layout = make_layout(progress)

        with Live(layout, console=console) as live:
            console = live.console
            logs = deque(maxlen=max(5, (console.height or 24) - 6))

            def update_progress():
                layout["progress"].update(make_progress_panel(progress))

            def update_messages():
                layout["messages"].update(make_messages_panel(logs))

            def log(msg, update: bool = True):
                logger.debug(msg)
                logs.append(msg)
                if update:
                    update_messages()

            try:
                save_path = Path("saved").expanduser().absolute().resolve()
                save_path.mkdir(parents=True, exist_ok=True)

                # Determine current logged in user
                current_user = DotMap(await (await session.get("users/@me")).json())
                log(
                    Text.from_markup(
                        f"Logged in as: [bold cyan]{current_user.global_name or current_user.username}[/cyan bold] <{current_user.id}@{current_user.phone or current_user.email}>",
                    )
                )

                # Gather all quests from server
                quests = list(await get_all_quests(session))
                enrollabe_quests = list(filter(Filters.Enrollable, quests))
                unclaimed_quests = list(filter(Filters.Claimable, quests))
                uncompleted_quests = list(filter(Filters.Completeable, quests))

                saved_as = save_data(
                    {
                        "user": current_user,
                        "quests": quests,
                        "enrollabe_quests": enrollabe_quests,
                        "unclaimed_quests": unclaimed_quests,
                        "uncompleted_quests": uncompleted_quests,
                    },
                    save_path
                    / f"{datetime.now().strftime('%d-%m-%Y_%M,%H,%S')}-quest-info.json",
                )
                log("Saved quest info in: {}".format(saved_as.relative_to(Path(".").expanduser().resolve())))

                if unclaimed_quests:
                    log(
                        Text(
                            f"You have {len(unclaimed_quests)} unclaimed quests",
                            style="bold yellow",
                        )
                    )

                if enrollabe_quests:
                    log(
                        Text(
                            f"You have {len(enrollabe_quests)} un-enrolled quests",
                            style="bold green",
                        )
                    )
                    for quest in enrollabe_quests:
                        user_status = await enroll_quest(quest, session)

                        if not user_status:
                            log(
                                Text(
                                    f"[{determine_quest_type(quest).name}] Unable to enroll in: {get_quest_name(quest)}",
                                    style="italic red",
                                )
                            )
                        else:
                            log(
                                Text(
                                    f"[{determine_quest_type(quest).name}] Enrolled in: {get_quest_name(quest)}",
                                    style="italic green",
                                )
                            )
                            quest.user_status = user_status
                            uncompleted_quests.append(quest)

                    uncompleted_quests = list(
                        filter(Filters.Completeable, uncompleted_quests)
                    )

                # Sort
                uncompleted_quests.sort(key=determine_quest_type, reverse=True)

                # Only process specific reward quests
                uncompleted_quests = list(filter(Filters.Worthy, uncompleted_quests))

                if not uncompleted_quests:
                    log("You have nothing to do.")
                    log("Bye bye 👋🏻👋🏻")
                    return

                def updater(name: str, done: int, total: int, task_id: TaskID):
                    cap: int = (console.width or 24) // 3 - 10
                    progress.update(
                        task_id,
                        description=name[:cap] + ("..." if len(name) > cap else ""),
                        total=total,
                        completed=done,
                    )

                for idx, quest in enumerate(uncompleted_quests):
                    task_id = progress.add_task(
                        description="Initilizing...", total=None
                    )
                    progress.columns = get_progress_columns()

                    update_progress()
                    task = asyncio.create_task(
                        complete_quest(
                            quest,
                            session,
                            procCallback=lambda name, done, total: updater(
                                name, done, total, task_id
                            ),
                            log=lambda msg: log(
                                Text(
                                    msg,
                                    style=f"{'Quest completed' in msg and 'green bold' or 'white italic'}",
                                    justify="left",
                                    overflow="ellipsis",
                                    no_wrap=True,
                                ),
                                False,
                            ),
                        )
                    )

                    while not task.done():
                        update_messages()
                        await asyncio.sleep(1)

                    # Remove taks if not last
                    if idx != len(uncompleted_quests) - 1:
                        progress.remove_task(task_id)
                    else:
                        progress.stop_task(task_id)

                    update_progress()
            except KeyboardInterrupt:
                return
            except Exception:
                console.print_exception()


if __name__ == "__main__":
    asyncio.run(main())
