from argparse import ArgumentParser
import asyncio
from datetime import datetime
from pathlib import Path
import re
from uuid import uuid4

import aiohttp
from pydotmap import DotMap

from consts import DATE_FORMAT, HEADERS, LOG_FORMAT, LOG_PATH, SUPER_PROPERTIES
from helpers import base64_encode, dump_json, get_logger, save_data
from logic import (
    Filters,
    complete_quest,
    enroll_quest,
    get_json,
    get_quest_name,
    get_quest_progress,
    get_quest_rewards,
    get_quest_type,
    get_quests,
)
from ui import (
    Progress,
    Console,
    TaskID,
    Text,
    get_quest_progress_columns,
    make_progress,
    make_quests_table,
    ROUNDED,
)

logger = get_logger(__name__, LOG_PATH / "completer.log", LOG_FORMAT, DATE_FORMAT)


async def change_heartbeat_id(session: aiohttp.ClientSession):
    while True:
        await asyncio.sleep(30 * 60)
        new_heartbeat_id = str(uuid4())
        SUPER_PROPERTIES["client_heartbeat_session"] = new_heartbeat_id
        session.headers.update(
            {"X-Super-Properties": base64_encode(dump_json(SUPER_PROPERTIES))}
        )
        logger.debug("Changed heartbeat session id")


async def update_headers(session: aiohttp.ClientSession):
    raw_html = await (await session.get("/")).text()
    build_number_match = re.search(r""""BUILD_NUMBER":\s*"(\d+)""", raw_html)
    if build_number_match:
        SUPER_PROPERTIES["client_build_number"] = int(build_number_match.group(1))
    HEADERS["X-Super-Properties"] = base64_encode(dump_json(SUPER_PROPERTIES))

    session.headers.update(HEADERS)


async def main(ap: ArgumentParser):
    async with aiohttp.ClientSession(
        base_url="https://discord.com/api/v10/", raise_for_status=True
    ) as session:
        await update_headers(session)

        console = Console()
        me = DotMap(await get_json(await session.get("users/@me")))

        # Argument parsing
        args = ap.parse_args()
        verbose = args.verbose
        save = args.save_data
        show_table = args.show_table

        if show_table:
            quests = await get_quests(session)
            table = make_quests_table(
                sorted(
                    quests,
                    key=lambda x: (Filters.NotExpired(x), -get_quest_progress(x)[1]),
                ),
                title=f"{me.global_name or me.username}'s Quests",
                highlight=True,
                box=ROUNDED,
                show_lines=True,
            )

            console.print(table)
            return

        asyncio.create_task(change_heartbeat_id(session))

        with make_progress(console=console) as progress:
            _tween_queue: asyncio.Queue[object | tuple[TaskID, str, int, int]] = (
                asyncio.Queue()
            )
            _current_values: dict[TaskID, int] = {}
            _sential = object()

            async def progress_worker(progress: Progress, speed: float = 2e-1):
                while (item := await _tween_queue.get()) and item is not _sential:
                    if not isinstance(item, tuple):
                        break

                    task_id, name, done, total = item
                    if task_id not in progress.task_ids:
                        _tween_queue.task_done()
                        continue

                    current = _current_values.get(task_id, 0)

                    # Update static fields immediately
                    progress.update(task_id, description=name, total=total)

                    # Tween smoothly
                    while current < done:
                        step = max(1, (done - current) // 8)  # easing
                        current += step
                        if current > done:
                            current = done

                        _current_values[task_id] = current
                        progress.update(task_id, completed=current)

                        await asyncio.sleep(speed)

                    _current_values[task_id] = done
                    _tween_queue.task_done()

                if item:
                    _tween_queue.task_done()

            def update_progress():
                progress.refresh()

            def log(*msgs: Text | str, important: bool = True):
                to_console, to_log = [], []

                for msg in msgs:
                    if isinstance(msg, Text):
                        to_log.append(msg.plain)
                    else:
                        to_log.append(msg)
                        msg = Text.from_markup(msg)

                    msg.truncate(progress.console.width, overflow="ellipsis")
                    to_console.append(msg)

                logger.debug(to_log)
                if not (verbose or important):
                    return

                progress.console.print(*to_console, sep="\n")

            try:
                # Start the Queue Worker
                asyncio.create_task(progress_worker(progress, 1e-1))

                save_path = Path("saved").expanduser().absolute().resolve()
                save_path.mkdir(parents=True, exist_ok=True)

                # get_quest_type current logged in user
                log(
                    Text.from_markup(
                        f"Logged in as: [bold cyan]{me.global_name or me.username}[/] <{me.id}@{me.phone or me.email}>",
                    )
                )

                async def wrapper_quest_complete(idx, quest):
                    task_id = progress.add_task(
                        description="Initilizing...", total=None
                    )
                    # Resets the spinner of progress bar
                    progress.columns = get_quest_progress_columns()

                    update_progress()
                    await complete_quest(
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
                            important="Quest completed" in msg,
                        ),
                    )

                    # Remove taks if not last
                    if idx != len(uncompleted_quests) - 1:
                        progress.remove_task(task_id)
                    else:
                        progress.stop_task(task_id)

                    update_progress()

                max_retry = 2
                counter = 0
                while counter < max_retry:
                    # Gather all quests from server
                    quests = list(await get_quests(session))
                    enrollabe_quests = list(filter(Filters.Enrollable, quests))
                    unclaimed_quests = list(filter(Filters.Claimable, quests))
                    uncompleted_quests = list(filter(Filters.Completeable, quests))

                    if save:
                        saved_as = save_data(
                            {
                                "user": me,
                                "quests": quests,
                                "enrollabe_quests": enrollabe_quests,
                                "unclaimed_quests": unclaimed_quests,
                                "uncompleted_quests": uncompleted_quests,
                            },
                            save_path
                            / f"{me.id}-{datetime.now().strftime('%d-%m-%Y_%M,%H,%S')}-quest-info.json",
                        )
                        log(
                            "Saved quest info in: {}".format(
                                saved_as.relative_to(Path(".").expanduser().resolve())
                            ),
                            important=False,
                        )

                    if unclaimed_quests:
                        quest_names = map(
                            lambda x: Text.from_markup(
                                f"[bold yellow]+[/] [{x.id}] [bold yellow]{get_quest_name(x)}[/]: {list(get_quest_rewards(x))}"
                            ),
                            unclaimed_quests,
                        )
                        log(
                            Text.from_markup(
                                f"[bold yellow]{len(unclaimed_quests)} Unclaimed quests[/]:",
                            ),
                            *quest_names,
                        )

                    if enrollabe_quests:
                        log(
                            Text.from_markup(
                                f"[bold green]{len(enrollabe_quests)} Un-enrolled quests[/]:",
                            )
                        )
                        all_enrolled = False
                        for quest in enrollabe_quests:
                            user_status = await enroll_quest(quest, session)

                            if not user_status:
                                log(
                                    Text.from_markup(
                                        f"[bold red]-[/] [{get_quest_type(quest).name}] Unable to enroll in: "
                                        f"[bold red]"
                                        f"{get_quest_name(quest)}"
                                        f"[/]"
                                    )
                                )
                                all_enrolled = False
                            else:
                                log(
                                    Text.from_markup(
                                        f"[bold green]+[/] [{get_quest_type(quest).name}] Enrolled in: "
                                        f"[bold green]"
                                        f"{get_quest_name(quest)} "
                                        f"[/]"
                                        f"{list(get_quest_rewards(quest))}"
                                    )
                                )
                                quest.user_status = user_status
                                uncompleted_quests.append(quest)
                                all_enrolled = True

                        if not all_enrolled:
                            counter += 1

                        # Restart
                        continue

                    # Only process specific reward quests [orbs, decorations](Filters.Worthy)
                    worthy_uncompleted_quests = list(
                        filter(Filters.Worthy, uncompleted_quests)
                    )
                    less_worthy_uncompleted_quuests = list(
                        filter(lambda x: not Filters.Worthy(x), uncompleted_quests)
                    )

                    # Sort
                    worthy_uncompleted_quests.sort(key=get_quest_type, reverse=True)
                    less_worthy_uncompleted_quuests.sort(
                        key=get_quest_type, reverse=True
                    )

                    if not (
                        worthy_uncompleted_quests or less_worthy_uncompleted_quuests
                    ):
                        log("You have nothing to do.")
                        log("Bye bye 👋🏻👋🏻")
                        return

                    def updater(name: str, done: int, total: int, task_id: TaskID):
                        cap: int = (console.width or 24) // 3 - 10
                        description = name[:cap] + ("..." if len(name) > cap else "")
                        _tween_queue.put_nowait((task_id, description, done, total))

                    log(
                        Text.from_markup(
                            f"Processing {len(worthy_uncompleted_quests)} "
                            "[bold cyan]worthy[/] quests..."
                        )
                    )
                    for idx, quest in enumerate(worthy_uncompleted_quests):
                        await wrapper_quest_complete(idx, quest)

                    log(
                        Text.from_markup(
                            f"Processing {len(less_worthy_uncompleted_quuests)} "
                            "[italic yellow]less worthy[/] quests..."
                        )
                    )
                    for idx, quest in enumerate(less_worthy_uncompleted_quuests):
                        await wrapper_quest_complete(idx, quest)

                    # Stop the queue_worker and be done
                    await _tween_queue.put(_sential)
                    # Wait until all item/progress_updates are applied
                    await _tween_queue.join()
                    break
            except (KeyboardInterrupt, asyncio.CancelledError):
                return
            except Exception:
                console.print_exception()


if __name__ == "__main__":
    parser = ArgumentParser(
        prog="Discord Quest Completer",
        description="Completes discord quests",
        add_help=False,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="Increase verbosity of quest completions progress",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "-s",
        "--save-data",
        help="Saves the data into a json file (user_info, quests)",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "-t",
        "--show-table",
        action="store_true",
        default=False,
        help="Shows the quests as a table for current user and exit",
    )
    parser.add_argument(
        "-h", "--help", "-?", help="Shows the help message and exit", action="help"
    )

    asyncio.run(main(parser))
