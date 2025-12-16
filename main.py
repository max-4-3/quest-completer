import asyncio, json, logging, re
from logging.handlers import RotatingFileHandler
from collections import deque
from collections.abc import Iterable, Iterator
from pathlib import Path
from time import sleep
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

LOG_FORMAT = (
    "%(asctime)s | "
    "%(levelname)-8s | "
    "%(name)s:%(lineno)d | "
    "%(message)s"
)

DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

handler = RotatingFileHandler(
    "global.log",
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


def save_data(data, path):
    path = Path(path).with_suffix(".json")
    tmp = path.with_suffix(".json.tmp")

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(normalize(data), f, indent=2, ensure_ascii=False)

    tmp.replace(path)


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

        with Console() as console:
            try:
                save_path = Path("saved").expanduser().absolute().resolve()
                save_path.mkdir(parents=True, exist_ok=True)

                # Gather all quests from server
                quests = list(await get_all_quests(session))
                enrollabe_quests = list(filter(Filters.Enrollable, quests))
                unclaimed_quests = list(filter(Filters.Claimable, quests))
                uncompleted_quests = list(
                    sorted(
                        filter(Filters.Completeable, quests),
                        key=determine_quest_type,
                        reverse=True,
                    )
                )

                if unclaimed_quests:
                    console.print("You got some unclaimed quests.")
                    console.print(
                        make_quests_table(unclaimed_quests, title="UnClaimed Quests")
                    )

                if enrollabe_quests:
                    console.print("You have some unenrolled quests.")
                    console.print(
                        make_quests_table(enrollabe_quests, title="UnEnrolled Quests")
                    )
                    console.print("Enrolling...")
                    for quest in enrollabe_quests:
                        await enroll_quest(quest, session)
                        console.print("Enrolled in '{}'".format(get_quest_name(quest)))
                        await asyncio.sleep(1)
                    return

                if not uncompleted_quests:
                    console.print("You have nothing to do.")
                    console.print("Bye bye 👋🏻👋🏻")
                    return

                console.print("Completing following quests.")
                console.print(
                    make_quests_table(uncompleted_quests, title="Active Quests")
                )

                logs = deque(maxlen=console.height - 1)

                def updater(name: str, done: int, total: int, task_id: TaskID):
                    task = progress.tasks[task_id]

                    if not task.started:
                        progress.start_task(task_id)

                    progress.update(
                        task_id,
                        description=name[:30] + ("..." if len(name) > 30 else ""),
                        total=total,
                    )

                    delta = done - task.completed
                    if delta > 0:
                        progress.advance(task_id, delta)

                progress = Progress(
                    SpinnerColumn("arc", finished_text="😋"),
                    TextColumn(
                        "{task.description}",
                        style="italic cyan bold",
                        markup=False,
                        highlighter=None,
                    ),
                    BarColumn(),
                    MofNCompleteColumn(),
                    console=console,
                    expand=True,
                )
                layout = Layout()
                layout.split_column(
                    Layout(name="messages", ratio=1), Layout(name="progress", size=4)
                )

                def update_messages():
                    layout["messages"].update(
                        Panel(
                            Group(*logs),
                            title="Messages",
                            title_align="center",
                            style="magenta bold",
                            border_style="yellow",
                            expand=True,
                        )
                    )

                def update_progress_layout():
                    layout["progress"].update(
                        Panel(
                            Group(progress),
                            title="Progress",
                            title_align="left",
                            style="bold green",
                            border_style="bold cyan",
                            expand=True,
                        )
                    )

                with Live(layout, refresh_per_second=10, console=console):
                    update_progress_layout()
                    update_messages()

                    for quest in uncompleted_quests:
                        task_id = progress.add_task(
                            description="Initilizing...", start=False
                        )
                        task = asyncio.create_task(
                            complete_quest(
                                quest,
                                session,
                                lambda name, done, total: updater(
                                    name, done, total, task_id
                                ),
                                lambda msg: logger.debug(msg)
                                or logs.append(
                                    Text(
                                        msg,
                                        style="magenta italic",
                                        justify="left",
                                        overflow="ellipsis",
                                        no_wrap=True,
                                    )
                                ),
                            )
                        )
                        while not task.done():
                            update_messages()
                            update_progress_layout()
                            await asyncio.sleep(1)

                        quest.completed = task.result()
                        progress.remove_task(task_id)
            except KeyboardInterrupt:
                return
            except Exception:
                console.print_exception()
                return


if __name__ == "__main__":
    asyncio.run(main())
