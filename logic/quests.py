import asyncio
from datetime import datetime
import json
import math
import random
from typing import Optional
from uuid import uuid4

from yarl import URL
from aiohttp import ClientSession
from pydotmap import DotMap

from logic.objects import (
    Filters,
    Logger,
    PrefixProgressCallback,
    ProgressCallback,
    QuestType,
)
from logic.registry import Registrar
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


async def get_orbs_balance(session: ClientSession):
    balance = None

    async with session.get(
        "users/@me/virtual-currency/balance", raise_for_status=False
    ) as resp:
        if resp.ok and "json" in resp.content_type:
            balance = int((await resp.json()).get("balance", "-1"))

    return balance or -1


@Registrar.register(QuestType.Achievement)
async def complete_achievement_quest(
    quest: DotMap,
    session: ClientSession,
    procCallback: ProgressCallback,
    log: Logger,
):
    quest_id, activity_id = quest.config.id, quest.config.application.id

    task_name, done, needed = get_quest_progress(quest)
    enrolled_at = quest.user_status.enrolled_at
    completed = done < needed

    perc = (done / needed) if needed else 0.0
    log(
        f"[{quest_id}] "
        f"{task_name}: {done}/{needed} ({completed = })"
        f"({perc * 100:.1f}%) | "
        f"Started: {datetime.fromisoformat(enrolled_at)} | "
        f"Rewards: {','.join(get_quest_rewards(quest))}"
    )

    resp = await get_json(await session.post(f"applications/{activity_id}/proxy-tickets", json={}))
    log(f"[{quest_id}] proxy-tickets resp for '{activity_id}': {resp}")
    _ticket = resp.get("ticket", None)
    if _ticket is None:
        raise ValueError(f"proxy-tickets request doesn't have ticket: {resp}")
    log(f"[{quest_id}] proxy tickets for '{activity_id}': {_ticket}")

    resp = await get_json(
        await session.post(
            f"oauth2/authorize",
            json={
                "authorize": True,
                "integration_type": 1,
            },
            params={
                "client_id": activity_id,
                "response_type": "code",
                "scope": "identify",
                "state": "",
            },
        )
    )
    log(f"[{quest_id}] oauth2 code resp for '{activity_id}': {resp}")
    _code: str | None = (URL(_loc).query.get("code", None)) if (_loc := resp.get("location", None)) else None
    if _code is None:
        raise ValueError(f"oauth2 code request doesn't have a valid location (with code param): {resp}")
    log(f"[{quest_id}] oauth2 code for '{activity_id}': {_code}")

    ticket, env_id, code = str(_ticket), str(uuid4()), str(_code)
    log(
        f"[{quest_id}] "
        f"Variables: {ticket = }; {env_id = }; {code = }"
    )

    async with ClientSession(
        base_url=f"https://{activity_id}.discordsays.com/.proxy/",
        headers={
            "X-Discord-Activity-Id": activity_id,
            "X-Discord-Hostname": f"{activity_id}.discordsays.com",
            "X-Discord-Quest-Id": quest_id,
            "X-Universe-Id": env_id
        },
    ) as proxy:

        # resp = await proxy.get("/", params={
        #     "instance_id": "example-cl-instance",
        #     "discord_proxy_ticket": ticket,
        #     "frame_id": str(uuid4())
        # })
        # auth_token = resp.cookies.get("discord_proxy_token")

        resp = await get_json(
            await proxy.post(
                f"acf/authorize",
                json={"activityId": activity_id, "code": code},
            )
        )
        log(f"[{quest_id}] auth token resp for '{activity_id}': {resp}")
        _auth_token: str | None = resp.get("token", None)
        if _auth_token is None:
            raise ValueError(f"auth token request doesn't have a valid token: {resp}")
        log(f"[{quest_id}] auth token for '{activity_id}': {_auth_token}")
        proxy.headers.add("X-Auth-Token", _auth_token)

        while not completed:
            await proxy.post(
                "api/presence/heartbeat",
                raise_for_status=True,
                json={"environmentId": env_id, "joinedLocation": True},
            )

            resp = await get_json(
                await proxy.post(
                    f"acf/quest/progress",
                    json={"progress": done},
                )
            )
            log(f"[{quest_id}] progress({done}/{needed}) resp for '{activity_id}': {resp}")
            _status: str | None = resp.get("status", None)
            if _status is None:
                raise ValueError(f"progress({done}/{needed}) request doesn't have a valid status: {resp}")
            log(f"[{quest_id}] progress status for '{activity_id}': {_status}")

            if _status != "ok":
                log(f"[{quest_id}] Not ok progress status for '{activity_id}' at {done}")
                continue

            done += 1
            procCallback(done, needed)
            completed = done >= needed

            if done > needed * 0.8:  # Last 20%
                interval = random.uniform(2, 3)
            else:
                interval = random.uniform(4, 6)

            await asyncio.sleep(interval)

        if done < needed:
            resp = await get_json(
                await proxy.post(
                    f"acf/quest/progress",
                    json={"progress": needed},
                )
            )
            log(f"[{quest_id}] progress({done}/{needed}) resp for '{activity_id}': {resp}")
            _status: str | None = resp.get("status", None)
            if _status is None:
                raise ValueError(f"progress({done}/{needed}) request doesn't have a valid status: {resp}")
            log(f"[{quest_id}] progress status for '{activity_id}': {_status}")

            if _status != "ok":
                log(f"[{quest_id}] Not ok progress status for '{activity_id}' at {done}")
            else:
                completed = True

    log(f"[{quest.id}] Quest completed but it might take some time to show up as completed!")
    procCallback(needed, needed)


@Registrar.register(QuestType.Watch)
async def complete_video_quest(
    quest: DotMap,
    session: ClientSession,
    procCallback: ProgressCallback,
    log: Logger,
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
            f"quests/{quest.id}/video-progress", json={"timestamp": seconds_needed}
        )

    log(f"[{quest.id}] Quest completed at {time_curr().isoformat()}!")
    procCallback(seconds_needed, seconds_needed)

    return True


@Registrar.register(QuestType.Play)
async def complete_play_quest(
    quest: DotMap,
    session: ClientSession,
    procCallback: ProgressCallback,
    log: Logger,
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
    procCallback: PrefixProgressCallback,
    log: Logger,
) -> Optional[bool]:
    quest_type = get_quest_type(quest)
    quest_name = get_quest_name(quest, quest_type).title()

    if not Registrar.available(quest_type):
        log(f"Unsupported Quest '{quest.id}' of type '{quest_type.name}'")
        procCallback(quest_name, 0, 0)
        return False

    if not Filters.Completeable(quest):
        log(f"Uncompleteable Quest '{quest.id}' of type '{quest_type}'")
        procCallback(quest_name, 0, 0)
        return False

    if quest_type == QuestType.Unknown:
        log(f"Unknown Quest '{quest.id}' of type '{quest_type.name}'")
        procCallback(quest_name, 0, 0)
        return False

    completer = Registrar.retrive(quest_type)
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
