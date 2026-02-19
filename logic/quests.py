import asyncio
from collections.abc import Callable
from datetime import datetime
import json
import math
import random
from typing import Optional

from aiohttp import ClientSession
from pydotmap import DotMap

from logic.objects import Filters, QuestCompleter, QuestType
from logic.utils import (
    time_curr,
    time_diff_now,
    time_in_past,
)
from logic.helpers import (
    get_json,
    get_quest_type,
    get_quest_name,
    get_quest_rewards,
    get_quest_progress,
)


async def complete_video_quest(
    quest: DotMap,
    session: ClientSession,
    procCallback: Callable[[int, int], None],
    log: Callable[[str], None],
):
    user_status = quest.user_status
    task_name, seconds_done, seconds_needed = get_quest_progress(quest)

    max_future, speed, interval = 1e1, 7, 1
    enrolled_at = user_status.enrolled_at
    completed = False

    perc = (seconds_done / seconds_needed) if seconds_needed else 0.0
    log(
        f"[{quest.id}] "
        f"{task_name}: {seconds_done}/{seconds_needed}s "
        f"({perc * 100:.1f}%) | "
        f"Started: {datetime.fromisoformat(enrolled_at)} | "
        f"Rewards: {','.join(get_quest_rewards(quest))}"
    )

    while not completed:
        if not time_in_past(enrolled_at):
            continue

        max_allowed = time_diff_now(enrolled_at).seconds + max_future
        diffrence = max_allowed - seconds_done
        next_ = seconds_done + speed

        if diffrence >= speed:
            server_response = DotMap(
                await get_json(
                    await session.post(
                        f"quests/{quest.id}/video-progress",
                        json={
                            "timestamp": min(seconds_needed, next_ + random.random())
                        },
                    )
                )
            )
            completed = server_response.completed_at is not None
            seconds_done = min(seconds_needed, next_)
            log(f"[{quest.id}] Heartbeat sent got reply: {server_response}")

        procCallback(seconds_done, seconds_needed)
        if seconds_done >= seconds_needed:
            break

        log(f"[{quest.id}] Sleeping for {interval:.0f}s...")

        log_interval = 10
        start = asyncio.get_running_loop().time()
        end = start + interval

        if log_interval > interval:
            await asyncio.sleep(interval)
        else:
            while True:
                remaining = end - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break

                log(f"[{quest.id}] {remaining:.0f}s remaining...")
                await asyncio.sleep(min(log_interval, remaining))

    if not completed:
        await session.post(
            f"quests/{quest.id}/heartbeat", json={"timestamp": seconds_needed}
        )

    log(f"[{quest.id}] Quest completed at {time_curr().isoformat()}!")
    procCallback(seconds_needed, seconds_needed)

    return True


async def complete_play_quest(
    quest: DotMap,
    session: ClientSession,
    procCallback: Callable[[int, int], None],
    log: Callable[[str], None],
) -> bool:
    user_status = quest.user_status
    task_name, seconds_done, seconds_needed = get_quest_progress(quest)

    interval = random.uniform(55, 70)
    enrolled_at = user_status.enrolled_at
    completed = False

    application_id = quest.id  # 🙂
    request_body = {"application_id": application_id, "terminal": False}

    perc = (seconds_done / seconds_needed) if seconds_needed else 0.0
    log(
        f"[{quest.id}] "
        f"{task_name}: {seconds_done}/{seconds_needed}s "
        f"({perc * 100:.1f}%) | "
        f"Started: {datetime.fromisoformat(enrolled_at)} | "
        f"Rewards: {','.join(get_quest_rewards(quest))}"
    )

    def get_seconds_response(data: DotMap) -> int:
        return (
            data.streamProgressSeconds
            if quest.config.config_version == 1
            else math.floor(data.progress.PLAY_ON_DESKTOP.value)
        )

    while not completed:
        server_response = DotMap(
            await get_json(
                await session.post(
                    f"quests/{application_id}/heartbeat", json=request_body
                )
            )
        )
        log(f"[{quest.id}] Heartbeat sent and got reply: {json.dumps(server_response)}")

        seconds_done = get_seconds_response(server_response)
        completed = server_response.completed_at is not None

        procCallback(seconds_done, seconds_needed)
        if seconds_done >= seconds_needed:
            break

        log(f"[{quest.id}] Sleeping for {interval:.0f}s...")

        if seconds_done > seconds_needed * 0.8:  # Last 20%
            interval = random.uniform(30, 45)
        else:
            interval = random.uniform(55, 70)

        log_interval = 10
        start = asyncio.get_running_loop().time()
        end = start + interval

        while True:
            remaining = end - asyncio.get_running_loop().time()
            if remaining <= 0:
                break

            log(f"[{quest.id}] {remaining:.0f}s remaining...")
            await asyncio.sleep(min(log_interval, remaining))

    if not completed:
        await session.post(f"quests/{application_id}/heartbeat", json=request_body)

    log(f"[{quest.id}] Quest completed at {time_curr().isoformat()}!")
    procCallback(seconds_needed, seconds_needed)

    return True


async def complete_quest(
    quest: DotMap,
    session: ClientSession,
    procCallback: Callable[[str, int, int], None],
    log: Callable[[str], None],
) -> Optional[bool]:
    quest_type = get_quest_type(quest)
    quest_name = get_quest_name(quest, quest_type).title()

    # TODO: Add more functions
    quest_map: dict[QuestType, QuestCompleter] = {
        QuestType.Watch: complete_video_quest,
        QuestType.Play: complete_play_quest,
    }

    if not Filters.Completeable(quest):
        log(f"Uncompleteable Quest '{quest.id}' of type '{quest_type}'")
        procCallback(quest_name, 0, 0)
        return False

    if quest_type == QuestType.Unknown:
        log(f"Unknown Quest '{quest.id}' of type '{quest_type.name}'")
        procCallback(quest_name, 0, 0)
        return False

    completer = quest_map.get(quest_type)
    if not completer:
        log(f"Unsupported Quest '{quest.id}' of type '{quest_type.name}'")
        procCallback(quest_name, 0, 0)
        return False

    log(
        f"[{quest_name}] Quest '{quest.id}' of type '{quest_type.name}' is supported "
        f"by '{completer.__name__}' "
        f"and now starting its completion."
    )

    return await completer(
        quest,
        session,
        lambda done, total: procCallback(
            f"[{quest_type.name}] {quest_name}", done, total
        ),
        log,
    )
