from datetime import datetime
from typing import Iterable, Optional

from aiohttp import ClientResponse, ClientSession
from pydotmap import DotMap

from logic.objects import Filters, QuestType


def get_quest_type(quest: DotMap) -> QuestType:
    return QuestType.from_quest(quest)


def get_quest_name(quest: DotMap, quest_type: Optional[QuestType] = None) -> str:
    quest_type = quest_type or get_quest_type(quest)
    application_name = quest.config.application.name

    if quest_type == QuestType.Watch:
        # Issue: #1
        try:
            return (
                quest.config.video_metadata.messages.video_title
                or f"Watch video by {application_name.title()}"
            )
        except AttributeError:
            pass

    return quest.config.messages.quest_name


def get_quest_progress(quest: DotMap, /):
    """TaskName, Done, Total"""
    task_config = quest.config.task_config or quest.config.task_config_v2
    done, total = 0, 100

    # Get when user_status is present
    if quest.user_status and len(quest.user_status.progress):
        task_name, done = max(
            map(lambda x: (x.event_name, x.value), quest.user_status.progress.values()),
            key=lambda x: x[1],
        )
        total = task_config.tasks[task_name].target
    else:
        task_name, total = min(
            map(lambda x: (x.event_name, x.target), task_config.tasks.values()),
            key=lambda x: x[1],
        )
        done = 0

    return task_name, done, total


def get_quest_rewards(quest: DotMap) -> Iterable[str]:
    rewards_config = quest.config.rewards_config.rewards
    return map(
        lambda s: str(s).title(),
        map(lambda x: x.messages.name_with_article, rewards_config),
    )


async def get_json(response: ClientResponse):
    return await response.json()


async def get_quests(session: ClientSession) -> Iterable[DotMap]:
    server_response = DotMap(
        await get_json(await session.get("quests/@me", raise_for_status=True))
    )

    if blocked := server_response.quest_enrollment_blocked_until:
        raise RuntimeError(
            f"You are blocked for completing any quests until: {datetime.fromisoformat(blocked)}"
        )

    excluded_quests = map(int, map(lambda x: x.id, server_response.excluded_quests))
    return filter(lambda x: x.id not in excluded_quests, server_response.quests)


async def enroll_quest(quest: DotMap, session: ClientSession) -> Optional[DotMap]:
    if not Filters.Enrollable(quest):
        return
    else:
        return await get_json(
            await session.post(
                f"quests/{quest.id}/enroll",
                json={"is_targeted": False, "location": 11, "metadata_raw": None},
                raise_for_status=True,
            )
        )
