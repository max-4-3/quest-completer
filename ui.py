from collections.abc import Iterable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import total_ordering
import logging

from rich.align import Align
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout

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


@total_ordering
class QuestType(Enum):
    UNKNOWN = -1
    ACHIEVEMENT = 0
    STREAM = 1
    ACTIVIY = 2
    PLAY = 3
    WATCH = 4

    def __lt__(self, other):
        if not isinstance(other, QuestType):
            return NotImplemented
        return self.value < other.value


@dataclass
class QuestUIState:
    name: str
    done: int
    total: int
    type: QuestType
    completed: bool = False
    completed_at: datetime = field(default_factory=lambda: datetime.max)


class QuestDashboard:
    def __init__(self, total_quests: list[QuestUIState]) -> None:
        self.tasks: dict[int, QuestUIState] = dict(enumerate(total_quests))
        self.current_tasks: dict[int, QuestUIState] = {}
        self.completed_tasks: dict[int, QuestUIState] = {}
        self.upcoming_tasks: dict[int, QuestUIState] = {}

        self.messages: list[Text] = []

        self._logger = logging.getLogger(__name__)

    def log_message(self, *message, log: bool = True):
        if log:
            self._logger.debug(message)
        self.messages.append(Text(" ".join(message), overflow="ellipsis"))

    def get_quests(self) -> dict[int, QuestUIState]:
        return self.tasks

    def set_completed(self, task_id: int):
        task = self.tasks[task_id]
        task.completed = True
        task.completed_at = datetime.now()
        self.completed_tasks[task_id] = task
        self.tasks[task_id] = task

        self._rebuild_views()

    def update_task(self, task_id: int, *, done: int, total: int = 0):
        task = self.tasks[task_id]
        task.done = done
        task.total = total or task.total

        if task.done >= task.total:
            task.completed = True
            task.completed_at = datetime.now()

        self.tasks[task_id] = task
        self._rebuild_views()

    @staticmethod
    def make_renderable_completed(task: QuestUIState) -> RenderableType:
        return Group(
            Text(
                f"✅ {task.name}",
                style="bold green",
                justify="left",
                overflow="ellipsis",
            )
        )

    @staticmethod
    def make_renderable_current(task: QuestUIState) -> RenderableType:
        return Group(
            Text(
                f"🏃🏻‍♀️ {task.name.title()} {(task.done / task.total if task.total else 0)*100:.1f}%",
                style="cyan",
                overflow="ellipsis",
                justify="full",
            )
        )

    @staticmethod
    def make_renderable_upcoming(task: QuestUIState) -> RenderableType:
        return Group(
            Text(f"⏳️ {task.name.title()}", overflow="ellipsis", justify="right", style="dim italic")
        )

    @staticmethod
    def create_empty():
        return Align.center(Text("None", style="dim"))

    @staticmethod
    def create_panel(group, **kwargs) -> Panel:
        return Panel(group, **kwargs)

    def _rebuild_views(self):
        self.completed_tasks.clear()
        self.current_tasks.clear()
        self.upcoming_tasks.clear()

        for task_id, task in self.tasks.items():
            if task.completed:
                self.completed_tasks[task_id] = task
            elif task.done > 0:
                self.current_tasks[task_id] = task
            else:
                self.upcoming_tasks[task_id] = task

    def render(self) -> Layout:
        layout = Layout()

        messages_layout = Layout(ratio=1, name="messages")
        tasks_layout = Layout(ratio=1, name="tasks")

        completed_layout = Layout(ratio=1, name="completed")
        current_layout = Layout(ratio=1, name="current")
        upcoming_layout = Layout(ratio=1, name="upcoming")

        # |  Messages  |
        # | C | A  | U |
        # C = completed_tasks, A = current_tasks, U = upcoming_tasks
        tasks_layout.split_row(completed_layout, current_layout, upcoming_layout)
        layout.split_column(messages_layout, tasks_layout)

        def update_layout_multiple_or_empty(
            layout: Layout, iteratable: Iterable, iter_mapper: Callable, **panel_kwargs
        ):
            if iteratable:
                layout.update(
                    self.create_panel(
                        Group(*map(iter_mapper, iteratable)), **panel_kwargs
                    )
                )
            else:
                layout.update(self.create_panel(self.create_empty(), **panel_kwargs))

        update_layout_multiple_or_empty(
            messages_layout, self.messages, lambda x: x, title="Messages"
        )
        update_layout_multiple_or_empty(
            completed_layout,
            self.completed_tasks.values(),
            self.make_renderable_completed,
            title="Completed",
            title_align="left",
            border_style="green",
        )
        update_layout_multiple_or_empty(
            current_layout,
            self.current_tasks.values(),
            self.make_renderable_current,
            title="Active",
            title_align="center",
            border_style="yellow",
        )
        update_layout_multiple_or_empty(
            upcoming_layout,
            self.upcoming_tasks.values(),
            self.make_renderable_upcoming,
            title="Upcoming",
            title_align="right",
            border_style="black",
        )

        return layout
