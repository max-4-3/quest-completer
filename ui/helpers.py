import random
from typing import Iterable
from pydotmap import DotMap
from logic import (
    get_quest_type,
    get_quest_name,
    get_quest_progress,
    get_quest_rewards,
    Filters,
)

from rich.console import Console, Group
from rich.layout import Layout
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
)
from rich.table import Table
from rich.text import Text

from ui.consts import SPINNERS, FINISHED_TEXTS


def make_quests_table(quests: Iterable[DotMap], **table_kwargs) -> Table:
    table = Table(**table_kwargs, expand=True)

    list(map(table.add_column, ["#", "Type", "Name", "Rewards", "Progress", "Expired"]))
    for idx, quest in enumerate(quests, 1):
        table.add_row(*[str(idx), *make_quest_renderables(quest)])

    return table


def make_quest_renderables(quest: DotMap, **text_kwargs):
    """Text: Type, Name, Rewards, Progress, Expired"""

    def percentage(x, y) -> str:
        if not all(isinstance(i, (int, float)) for i in [x, y]):
            return "0.00%"
        # if has higher presidence over artihmetic
        return f"{(x / y if y else 0) * 100:.2f}%"

    return map(
        lambda x: Text(x, **text_kwargs),
        map(
            str,
            [
                get_quest_type(quest).name,
                get_quest_name(quest).title(),
                ", ".join(get_quest_rewards(quest)),
                percentage(*get_quest_progress(quest)[1:]),
                not Filters.NotExpired(quest),
            ],
        ),
    )


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


def get_quest_progress_columns():
    return (
        SpinnerColumn(
            random.choice(SPINNERS), finished_text=random.choice(FINISHED_TEXTS)
        ),
        TextColumn(
            "{task.description}",
            style="italic cyan bold",
        ),
        BarColumn(None),
        MofNCompleteColumn(),
    )


def make_progress(console: Console):
    return Progress(
        *get_quest_progress_columns(),
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
