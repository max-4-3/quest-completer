import asyncio
from collections.abc import Iterator
from datetime import datetime, timezone
import json
import logging
import math as Math
from pathlib import Path
import random
import re
from typing import Callable
from uuid import uuid4

import aiohttp
from pydotmap import DotMap
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress

from const import HEADERS, SUPER_PROPERTIES, base64_encode, dump_json
from temp1 import make_state


logging.basicConfig(filename="session.log", filemode="a", level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
filehandler = logging.FileHandler("global.log", "a")
formatter = logging.Formatter()
filehandler.setFormatter(formatter)
logger.addHandler(filehandler)


def ui_log(msg: str):
    logger.debug(msg)


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


async def complete_play_quest(
    quest: DotMap,
    session: aiohttp.ClientSession,
    procCallback: Callable[[int, int], None],
) -> bool:
    application_id = quest.id
    task_config = quest.config.task_config or quest.config.task_config_v2
    request_body = {"application_id": application_id, "terminal": False}
    seconds_needed = task_config.tasks.PLAY_ON_DESKTOP.target

    # _ = DotMap(
    #     (
    #         await (
    #             await session.get(
    #                 f"applications/public?application_ids={application_id}"
    #             )
    #         ).json()
    #     )[0]
    # )

    def get_progress(data: DotMap) -> int:
        return (
            data.streamProgressSeconds
            if quest.config.config_version == 1
            else Math.floor(data.progress.PLAY_ON_DESKTOP.value)
        )

    while True:
        server_response = DotMap(
            await (
                await session.post(
                    f"quests/{application_id}/heartbeat", json=request_body
                )
            ).json()
        )
        ui_log("Heartbeat sent!")
        progress = get_progress(server_response)
        procCallback(progress, seconds_needed)

        if progress >= seconds_needed:
            return True

        await asyncio.sleep(random.random() * 10 + 60)


async def complete_video_quest(
    quest: DotMap,
    session: aiohttp.ClientSession,
    procCallback: Callable[[int, int], None],
) -> bool:
    task_config = quest.config.task_config or quest.config.task_config_v2
    user_status = quest.user_status
    task_name = list(task_config.tasks.keys())[0]
    task = task_config.tasks[task_name]

    seconds_needed = task.target
    seconds_done = (
        0 if len(user_status.progress) == 0 else user_status.progress[task_name].value
    )

    max_future, speed, interval = 1e1, 7, 1
    enrolled_at = datetime.fromisoformat(user_status.enrolled_at).timestamp()
    completed = False

    while not completed:
        max_allowed = (
            Math.floor((datetime.now(timezone.utc).timestamp() - enrolled_at))
            + max_future
        )
        diffrence = max_allowed - seconds_done
        next_ = seconds_done + speed

        if diffrence >= speed:
            server_response = DotMap(
                await (
                    await session.post(
                        f"quests/{quest.id}/video-progress",
                        json={
                            "timestamp": min(seconds_needed, next_ + random.random())
                        },
                    )
                ).json()
            )
            ui_log(f"Heartbeat sent!")
            completed = server_response.completed_at != None
            seconds_done = min(seconds_needed, next_)

        procCallback(seconds_done, seconds_needed)
        if seconds_done >= seconds_needed:
            break

        await asyncio.sleep(interval)

    if not completed:
        await session.post(
            f"quests/{quest.id}/heartbeat", json={"timestamp": seconds_needed}
        )
        procCallback(seconds_needed, seconds_needed)

    return True


async def complete_quest(
    quest: DotMap,
    session: aiohttp.ClientSession,
    procCallback: Callable[[str, int, int], None],
) -> bool:
    async with asyncio.Semaphore(1):
        task_map = {
            "WATCH_VIDEO": complete_video_quest,
            "WATCH_VIDEO_ON_MOBILE": complete_video_quest,
            "PLAY_ON_DESKTOP": complete_play_quest,
        }

        task_config = quest.config.task_config or quest.config.task_config_v2
        quest_tasks = set(task_config.tasks.keys())

        supported = quest_tasks & task_map.keys()
        if not supported:
            raise NotImplementedError(f"Unsupported tasks: {quest_tasks}")

        task_name = supported.pop()

        return await task_map[task_name](
            quest,
            session,
            lambda done, total: procCallback(task_name, done, total),
        )


async def change_heartbeat_id(session: aiohttp.ClientSession):
    while True:
        new_heartbeat_id = str(uuid4())
        SUPER_PROPERTIES["client_heartbeat_session"] = new_heartbeat_id
        session.headers.update(
            {"X-Super-Properties": base64_encode(dump_json(SUPER_PROPERTIES))}
        )
        ui_log("Changed heartbeat session id")
        await asyncio.sleep(30 * 60)


async def main():
    async with aiohttp.ClientSession(
        base_url="https://discord.com/api/v10/", raise_for_status=True
    ) as session:
        with Console() as console:
            asyncio.create_task(change_heartbeat_id(session))

            raw_html = await (await session.get("/")).text()
            save_path = Path("saved").expanduser()
            build_number_match = re.search(r""""BUILD_NUMBER":\s*"(\d+)""", raw_html)
            if build_number_match:
                SUPER_PROPERTIES["client_build_number"] = int(
                    build_number_match.group(1)
                )
            HEADERS["X-Super-Properties"] = base64_encode(dump_json(SUPER_PROPERTIES))

            session.headers.update(HEADERS)

            save_path.mkdir(parents=True, exist_ok=True)
            quests_response = DotMap(await (await session.get("quests/@me")).json())

            if quests_response.quest_enrollment_blocked_until:
                raise RuntimeError("Blocked from doing quests")

            excluded_quests_id = [item.id for item in quests_response.excluded_quests]

            def valid_quest(quest: DotMap) -> bool:
                user_status = quest.user_status or DotMap({})
                return not (
                    quest.id in excluded_quests_id
                    or quest.id == 1248385850622869556
                    or not user_status.enrolled_at
                    or user_status.completed_at
                    or datetime.fromisoformat(quest.config.expires_at)
                    < datetime.now(timezone.utc)
                )

            with Progress() as progress:

                hiashaishas = [(quest, make_state(quest)) for quest in filter(valid_quest, quests_response.quests)]
                hiashaishas.sort(key=lambda v: v[1].type, reverse=True)

                async def wrapper(quest, task_id):
                    def update(_, done, total):
                        progress.start_task(task_id)
                        progress.update(task_id, total=total, completed=done)
                        if done >= total:
                            progress.stop_task(task_id)

                    return await complete_quest(quest, session, update)

                for quest, state in hiashaishas:
                    task_id = progress.add_task(
                        f"[{state.type.name}] {state.name.title()[:30]}{len(state.name) > 30 and '...'}",
                        total=state.total,
                        completed=state.done,
                        start=False,
                    )
                    try:
                        await wrapper(quest, task_id)
                    except:
                        console.print_exception()
                        progress.remove_task(task_id)

                console.print("All tasks completed!", style="bold green")

if __name__ == "__main__":
    asyncio.run(main())
