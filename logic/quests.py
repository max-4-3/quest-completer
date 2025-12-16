from collections.abc import Awaitable, Iterable, Callable
from typing import Optional
from enum import Enum
from functools import total_ordering
import math, random, asyncio, json
from aiohttp import ClientSession, ClientResponse
from datetime import datetime, timezone
from pydotmap import DotMap


class Filters:
    Enrollable: Callable[[DotMap], bool] = lambda x: not x.user_status and is_active(x)
    Completeable: Callable[[DotMap], bool] = lambda x: (
        x.id != 1248385850622869556
        and x.user_status
        and x.user_status.enrolled_at
        and not x.user_status.completed_at
        and is_active(x)
    )

    Claimable: Callable[[DotMap], bool] = lambda x: bool(
        x.user_status
        and is_active(x)
        and x.user_status.completed_at
        and x.config.rewards_config.rewards_expire_at
        and datetime.fromisoformat(x.config.rewards_config.rewards_expire_at)
        < datetime.now(timezone.utc)
    )


@total_ordering
class QuestType(Enum):
    Unknown = -1
    Achievement = 0
    Stream = 1
    Activiy = 2
    Play = 3
    Watch = 4

    def __lt__(self, other):
        if not isinstance(other, QuestType):
            return NotImplemented
        return self.value < other.value


type QuestCompleter = Callable[
    [DotMap, ClientSession, Callable[[int, int], None], Callable[[str], None]],
    Awaitable[Optional[bool]],
]


async def get_json(response: ClientResponse):
    return await response.json()


def is_active(quest: DotMap) -> bool:
    return datetime.fromisoformat(quest.config.expires_at) > datetime.now(timezone.utc)

def get_progress(quest: DotMap, extra_info: Optional[bool] = False):
    task_config = quest.config.task_config or quest.config.task_config_v2
    done, total = 0, 100
    
    # Get when user_status is present
    if quest.user_status and len(quest.user_status.progress):
        task_name, done = max(map(lambda x: (x.event_name, x.value), quest.user_status.progress.values()), key=lambda x: x[1])
        total = task_config.tasks[task_name].target
    else:
        task_name, total = min(map(lambda x: (x.event_name, x.target), task_config.tasks.values()), key=lambda x: x[1])
        done = 0

    if extra_info:
        return task_name, done, total
    else:
        return done, total

async def get_all_quests(session: ClientSession) -> Iterable[DotMap]:
    server_response = DotMap(
        await get_json(await session.get("quests/@me", raise_for_status=True))
    )
    if blocked := server_response.quest_enrollment_blocked_until:
        raise RuntimeError(f"You are blocked for completing any quests until: {datetime.fromisoformat(blocked)}")

    excluded_quests = map(int, map(lambda x: x.id, server_response.excluded_quests))
    return filter(lambda x: x.id not in excluded_quests, server_response.quests)


def get_rewards(quest: DotMap) -> Iterable[str]:
    rewards_config = quest.config.rewards_config.rewards
    return map(
        lambda s: str(s).title(),
        map(lambda x: x.messages.name_with_article, rewards_config),
    )


def get_quest_name(quest: DotMap, quest_type: Optional[QuestType] = None) -> str:
    quest_type = quest_type or determine_quest_type(quest)
    application_name = quest.config.application.name

    if quest_type == QuestType.Watch:
        return (
            quest.config.video_metadata.messages.video_title
            or f"Watch video by {application_name.title()}"
        )

    return quest.config.messages.quest_name


def determine_quest_type(quest: DotMap) -> QuestType:
    task_config = quest.config.task_config or quest.config.task_config_v2
    tasks_names = task_config.tasks.keys()
    if any(n.lower() == "play_activity" for n in tasks_names):
        return QuestType.Activiy

    match list(map(lambda x: x.lower().split("_")[0], tasks_names))[0]:
        case "watch":
            return QuestType.Watch
        case "play":
            return QuestType.Play
        case "stream":
            return QuestType.Stream
        case "achievement":
            return QuestType.Achievement
        case _:
            return QuestType.Unknown


async def enroll_quest(quest: DotMap, session: ClientSession) -> bool:
    def can_enroll(quest: DotMap) -> bool:
        return not quest.user_status and is_active(quest)

    return (
        can_enroll(quest)
        and (await session.post(f"quests/{quest.id}/enroll", raise_for_status=False)).ok
    )


async def complete_video_quest(
    quest: DotMap,
    session: ClientSession,
    procCallback: Callable[[int, int], None],
    log: Callable[[str], None],
):
    user_status = quest.user_status
    task_name, seconds_done, seconds_needed = get_progress(quest, True) # pyright: ignore[reportAssignmentType]

    max_future, speed, interval = 1e1, 7, 1
    enrolled_at = datetime.fromisoformat(user_status.enrolled_at).timestamp()
    completed = False

    log(
        f"[{quest.id}] Completing video quest started at '{datetime.fromtimestamp(enrolled_at)}' for rewards '{','.join(get_rewards(quest))}' [{seconds_done}/{seconds_needed} @ {task_name}]"
    )
    while not completed:
        max_allowed = (
            math.floor((datetime.now(timezone.utc).timestamp() - enrolled_at))
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
            completed = server_response.completed_at != None
            seconds_done = min(seconds_needed, next_)
            log(f"[{quest.id}] Heartbeat sent got reply: {server_response}")

        procCallback(seconds_done, seconds_needed)
        if seconds_done >= seconds_needed:
            break

        log(f"[{quest.id}] Sleeping for {interval:.0f}s...")
        await asyncio.sleep(interval)

    if not completed:
        await session.post(
            f"quests/{quest.id}/heartbeat", json={"timestamp": seconds_needed}
        )
        log(f"[{quest.id}] Quest completed!")
        procCallback(seconds_needed, seconds_needed)

    return True


async def complete_play_quest(
    quest: DotMap,
    session: ClientSession,
    procCallback: Callable[[int, int], None],
    log: Callable[[str], None],
) -> bool:
    application_id = quest.id  # 🙂
    request_body = {"application_id": application_id, "terminal": False}
    seconds_done, seconds_needed = get_progress(quest) # pyright: ignore[reportAssignmentType]

    log(
        f"[{quest.id}] Completing play quest started at '{datetime.fromisoformat(quest.user_status.enrolled_at)}' for rewards '{','.join(get_rewards(quest))}' [{seconds_done}/{seconds_needed} @ PLAY_ON_DESKTOP]"
    )

    def get_progress_response(data: DotMap) -> int:
        return (
            data.streamProgressSeconds
            if quest.config.config_version == 1
            else math.floor(data.progress.PLAY_ON_DESKTOP.value)
        )

    while True:
        server_response = DotMap(
            await (
                await session.post(
                    f"quests/{application_id}/heartbeat", json=request_body
                )
            ).json()
        )
        progress = get_progress_response(server_response)
        procCallback(progress, seconds_needed)
        log(f"[{quest.id}] Heartbeat sent and got reply: {json.dumps(server_response)}")

        if progress >= seconds_needed:
            procCallback(seconds_needed, seconds_needed)
            log(f"[{quest.id} Quest completed at '{datetime.now()}'")
            return True

        if progress > seconds_needed * 0.8:  # Last 20%
            sleep_time = random.uniform(30, 45)
        else:
            sleep_time = random.uniform(55, 70)
            
        log(f"[{quest.id}] Sleeping for {sleep_time:.0f}s...")
        await asyncio.sleep(sleep_time)


async def complete_quest(
    quest: DotMap,
    session: ClientSession,
    procCallback: Callable[[str, int, int], None],
    log: Callable[[str], None],
) -> Optional[bool]:
    quest_type = determine_quest_type(quest)
    quest_name = get_quest_name(quest, quest_type)
    if quest_type == QuestType.Unknown:
        log(f"Unknown Quest type '{quest_type.name}'")
        procCallback(quest_name, 0, 0)
        return False

    # TODO: Add more functions
    quest_map: dict[QuestType, QuestCompleter] = {
        QuestType.Watch: complete_video_quest,
        QuestType.Play: complete_play_quest,
    }

    completer = quest_map.get(quest_type)
    if not completer:
        log(f"Unsupported quest for completing: '{quest_type.name}'")
        procCallback(quest_name, 0, 0)
        return False

    quest_name = get_quest_name(quest, quest_type)
    log(
        f"Quest of type '{quest_type.name}' is supported and now starting its completion. [{quest_name}]"
    )
    return await completer(
        quest, session, lambda done, total: procCallback(quest_name, done, total), log
    )
