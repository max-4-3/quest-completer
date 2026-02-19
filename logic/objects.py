from collections.abc import Awaitable, Callable
from enum import Enum
from functools import total_ordering
from typing import Optional

from aiohttp import ClientSession
from pydotmap import DotMap

from logic.utils import time_in_past

type QuestFilter = Callable[[DotMap], bool]
type QuestCompleter = Callable[
    [DotMap, ClientSession, Callable[[int, int], None], Callable[[str], None]],
    Awaitable[Optional[bool]],
]


class Filters:
    NotExpired: QuestFilter = lambda x: not time_in_past(x.config.expires_at)
    Enrollable: QuestFilter = lambda x: (
        not x.user_status and not time_in_past(x.config.expires_at)
    )

    Completeable: QuestFilter = lambda x: (
        x.id != 1248385850622869556
        and x.user_status
        and x.user_status.enrolled_at
        and not x.user_status.completed_at
        and not time_in_past(x.config.expires_at)
    )

    Claimable: QuestFilter = lambda x: bool(
        x.user_status
        and not time_in_past(x.config.expires_at)
        and x.user_status.completed_at
        and not x.user_status.claimed_at
        and (rea := x.config.rewards_config.rewards_expire_at)
        and not time_in_past(rea)
    )

    # 3, 4 => Collectable, Orbs
    Worthy: QuestFilter = lambda x: bool(
        not time_in_past(x.config.expires_at)
        and any(reward.type in [3, 4] for reward in x.config.rewards_config.rewards)
    )


@total_ordering
class QuestType(Enum):
    Unknown = -1
    Achievement = 0
    Stream = 1
    Activiy = 2
    Play = 3
    Watch = 4

    @classmethod
    def from_quest(cls, quest: DotMap):
        task_config = quest.config.task_config or quest.config.task_config_v2
        tasks_names = task_config.tasks.keys()

        # Special Case
        if any(n.lower() == "play_activity" for n in tasks_names):
            return QuestType.Activiy

        # fmt:off
        type_map = {
            "watch"         : cls.Watch,
            "play"          : cls.Play,
            "stream"        : cls.Stream,
            "achievement"   : cls.Achievement,
            "unknown"       : cls.Unknown,
        }
        # fmt:on

        try:
            # "WATCH_VIDEO" => ["WATCH", "VIDEO"] => "WATCH"
            name = list(map(lambda x: x.split("_").pop(0), map(str, tasks_names))).pop(
                0
            )
        except IndexError:
            name = "Unknown"

        return type_map.get(name.lower(), cls.Unknown)

    def __lt__(self, other):
        if not isinstance(other, QuestType):
            return NotImplemented
        return self.value < other.value
