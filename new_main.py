import asyncio
from collections.abc import Iterator
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import random
import re
import sys
from time import sleep
from typing import Callable, Optional
from uuid import uuid4

import aiohttp
from pydotmap import DotMap
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
    TimeElapsedColumn,
)
from rich.panel import Panel
from rich.table import Table
import math

from const import HEADERS, SUPER_PROPERTIES, base64_encode, dump_json
from temp1 import make_state


# Setup file-only logging (no stdout)
def setup_logging():
    """Configure logging to write only to files, not stdout"""
    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler for session.log
    session_handler = logging.FileHandler(
        "session.log",
        mode="a",
        encoding="utf-8"
    )
    session_handler.setLevel(logging.DEBUG)
    session_handler.setFormatter(formatter)
    
    # File handler for global.log
    global_handler = logging.FileHandler(
        "global.log",
        mode="a",
        encoding="utf-8"
    )
    global_handler.setLevel(logging.DEBUG)
    global_handler.setFormatter(formatter)
    
    # Add handlers
    root_logger.addHandler(session_handler)
    root_logger.addHandler(global_handler)

# Initialize logging
setup_logging()
logger = logging.getLogger(__name__)

# Create console instance for UI (progress bars only, no logs)
console = Console()


class QuestLogger:
    """Custom logger for quest operations - UI output only, no file logging"""
    
    def __init__(self, quest_name: str, quest_type: Optional[str] = None):
        self.quest_name = quest_name
        self.quest_type = quest_type
        self.session_id = str(uuid4())[:8]
        
    def _format_message(self, message: str, level: str = "INFO") -> str:
        timestamp = datetime.now().strftime("%H:%M:%S")
        quest_display = f"{self.quest_type}:{self.quest_name}" if self.quest_type else self.quest_name
        return f"[{timestamp}] [{self.session_id}] [{level}] [{quest_display}] {message}"
    
    def info(self, message: str):
        """Display info message to UI only"""
        formatted = self._format_message(message, "INFO")
        # console.print(formatted, style="cyan")
        # Write to file log
        logger.info(formatted)
    
    def success(self, message: str):
        """Display success message to UI only"""
        formatted = self._format_message(message, "SUCCESS")
        # console.print(formatted, style="green bold")
        # Write to file log
        logger.info(f"SUCCESS: {formatted}")
    
    def warning(self, message: str):
        """Display warning message to UI only"""
        formatted = self._format_message(message, "WARNING")
        # console.print(formatted, style="yellow")
        # Write to file log
        logger.warning(formatted)
    
    def error(self, message: str):
        """Display error message to UI only"""
        formatted = self._format_message(message, "ERROR")
        # console.print(formatted, style="red bold")
        # Write to file log
        logger.error(formatted)
    
    def debug(self, message: str):
        """Display debug message to UI only (if debug mode enabled)"""
        formatted = self._format_message(message, "DEBUG")
        # console.print(formatted, style="dim")
        # Write to file log
        logger.debug(formatted)
    
    def progress(self, current: int, total: int, speed: Optional[float] = None):
        """Log progress with percentage - UI only for frequent updates"""
        percentage = (current / total) * 100 if total > 0 else 0
        message = f"Progress: {current}/{total} ({percentage:.1f}%)"
        if speed:
            message += f" | Speed: {speed:.1f}x"
        # Only show every 5th progress update to avoid spam
        if current % 5 == 0 or current == total:
            console.print(f"[dim]{self._format_message(message, 'PROGRESS')}[/dim]")
        # Always log to file
        logger.debug(message)


def normalize(obj):
    """Recursively normalize objects for JSON serialization"""
    if isinstance(obj, Iterator):
        return list(obj)
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [normalize(x) for x in obj]
    return obj


def save_data(data, path):
    """Save data to JSON file with atomic write"""
    path = Path(path).with_suffix(".json")
    tmp = path.with_suffix(".json.tmp")
    
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(normalize(data), f, indent=2, ensure_ascii=False, sort_keys=True)
        tmp.replace(path)
        logger.debug(f"Data saved to {path}")
    except Exception as e:
        logger.error(f"Failed to save data to {path}: {e}")
        if tmp.exists():
            tmp.unlink()


def create_progress_display() -> Progress:
    """Create a rich progress display with custom columns"""
    return Progress(
        SpinnerColumn("bounce"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        console=console,
        expand=True,
        refresh_per_second=10,  # Update frequency
    )


async def complete_play_quest(
    quest: DotMap,
    session: aiohttp.ClientSession,
    progress_callback: Callable[[int, int], None],
    quest_logger: QuestLogger,
) -> bool:
    """Complete a play quest"""
    application_id = quest.id
    task_config = quest.config.task_config or quest.config.task_config_v2
    request_body = {"application_id": application_id, "terminal": False}
    seconds_needed = task_config.tasks.PLAY_ON_DESKTOP.target
    
    quest_logger.info(f"Starting PLAY_ON_DESKTOP quest (ID: {application_id})")
    quest_logger.info(f"Target time: {seconds_needed} seconds")
    
    def get_progress(data: DotMap) -> int:
        return (
            data.streamProgressSeconds
            if quest.config.config_version == 1
            else math.floor(data.progress.PLAY_ON_DESKTOP.value)
        )
    
    heartbeat_count = 0
    start_time = datetime.now()
    
    while True:
        try:
            server_response = DotMap(
                await (
                    await session.post(
                        f"quests/{application_id}/heartbeat",
                        json=request_body
                    )
                ).json()
            )
            heartbeat_count += 1
            progress = get_progress(server_response)
            
            # Calculate ETA
            if progress > 0:
                elapsed = (datetime.now() - start_time).total_seconds()
                speed = progress / elapsed if elapsed > 0 else 0
                eta = (seconds_needed - progress) / speed if speed > 0 else 0
                quest_logger.progress(progress, seconds_needed, speed)
            else:
                quest_logger.progress(progress, seconds_needed)
            
            progress_callback(progress, seconds_needed)
            
            if progress >= seconds_needed:
                completion_time = datetime.now() - start_time
                quest_logger.success(
                    f"Quest completed in {completion_time.total_seconds():.0f} seconds "
                    f"({heartbeat_count} heartbeats)"
                )
                return True
            
            # Dynamic sleep based on progress
            if progress > seconds_needed * 0.8:  # Last 20%
                sleep_time = random.uniform(30, 45)
            else:
                sleep_time = random.uniform(55, 70)
            
            await asyncio.sleep(sleep_time)
            
        except Exception as e:
            quest_logger.error(f"Heartbeat failed: {e}")
            await asyncio.sleep(random.uniform(10, 20))


async def complete_video_quest(
    quest: DotMap,
    session: aiohttp.ClientSession,
    progress_callback: Callable[[int, int], None],
    quest_logger: QuestLogger,
) -> bool:
    """Complete a video quest"""
    task_config = quest.config.task_config or quest.config.task_config_v2
    user_status = quest.user_status
    task_name = list(task_config.tasks.keys())[0]
    task = task_config.tasks[task_name]
    
    seconds_needed = task.target
    seconds_done = (
        0 if len(user_status.progress) == 0 
        else user_status.progress[task_name].value
    )
    
    max_future, speed, interval = 1e1, 7, 1
    enrolled_at = datetime.fromisoformat(user_status.enrolled_at).timestamp()
    completed = False
    
    quest_logger.info(f"Starting {task_name} quest")
    quest_logger.info(f"Target: {seconds_needed} seconds | Already done: {seconds_done}")
    
    start_time = datetime.now()
    progress_updates = 0
    
    while not completed:
        try:
            max_allowed = (
                math.floor((datetime.now(timezone.utc).timestamp() - enrolled_at))
                + max_future
            )
            difference = max_allowed - seconds_done
            next_ = seconds_done + speed
            
            if difference >= speed:
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
                progress_updates += 1
                
                completed = server_response.completed_at is not None
                seconds_done = min(seconds_needed, next_)
                
                # Log progress periodically
                if progress_updates % 5 == 0:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    actual_speed = seconds_done / elapsed if elapsed > 0 else 0
                    quest_logger.progress(seconds_done, seconds_needed, actual_speed)
            
            progress_callback(seconds_done, seconds_needed)
            
            if seconds_done >= seconds_needed:
                completion_time = datetime.now() - start_time
                quest_logger.success(
                    f"Quest completed in {completion_time.total_seconds():.0f} seconds "
                    f"({progress_updates} updates)"
                )
                break
            
            await asyncio.sleep(interval)
            
        except Exception as e:
            quest_logger.error(f"Progress update failed: {e}")
            await asyncio.sleep(interval * 2)
    
    if not completed:
        try:
            await session.post(
                f"quests/{quest.id}/heartbeat",
                json={"timestamp": seconds_needed}
            )
        except Exception as e:
            quest_logger.warning(f"Final heartbeat failed: {e}")
        
        progress_callback(seconds_needed, seconds_needed)
    
    return True


async def complete_quest(
    quest: DotMap,
    session: aiohttp.ClientSession,
    progress_callback: Callable[[str, int, int], None],
    semaphore: asyncio.Semaphore,
) -> bool:
    """Complete a quest with proper resource management"""
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
    
    # Create quest-specific logger
    quest_name = quest.config.title if hasattr(quest.config, 'title') else f"Quest_{quest.id}"
    quest_logger = QuestLogger(quest_name[:30], task_name)
    
    async with semaphore:
        quest_logger.info("Starting quest execution")
        
        try:
            result = await task_map[task_name](
                quest,
                session,
                lambda done, total: progress_callback(task_name, done, total),
                quest_logger,
            )
            quest_logger.success("Quest completed successfully")
            return result
        except Exception as e:
            quest_logger.error(f"Quest failed: {e}")
            raise


async def change_heartbeat_id(session: aiohttp.ClientSession):
    """Periodically change heartbeat session ID"""
    # Use file logger directly for background tasks
    logger.info("Starting heartbeat ID rotation")
    
    while True:
        try:
            new_heartbeat_id = str(uuid4())
            SUPER_PROPERTIES["client_heartbeat_session"] = new_heartbeat_id
            session.headers.update(
                {"X-Super-Properties": base64_encode(dump_json(SUPER_PROPERTIES))}
            )
            logger.debug(f"Heartbeat session ID changed to: {new_heartbeat_id[:8]}...")
            await asyncio.sleep(30 * 60)  # 30 minutes
        except Exception as e:
            logger.error(f"Failed to change heartbeat ID: {e}")
            await asyncio.sleep(60)  # Retry after 1 minute


def display_quest_summary(quests_data):
    """Display a summary of available quests"""
    table = Table(title="📋 Available Quests", width=console.width, show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Type", width=15)
    table.add_column("Name", width=40)
    table.add_column("Progress", justify="right", width=15)
    table.add_column("Status", width=12)
    
    for idx, (quest, state) in enumerate(quests_data, 1):
        progress_text = f"{state.done}/{state.total}"
        percentage = (state.done / state.total * 100) if state.total > 0 else 0
        
        if percentage >= 100:
            status = "✅ Complete"
            style = "green"
        elif percentage > 0:
            status = "⏳ In Progress"
            style = "yellow"
        else:
            status = "🔵 Not Started"
            style = "blue"
        
        table.add_row(
            str(idx),
            state.type.name,
            state.name[:37] + "..." if len(state.name) > 37 else state.name,
            progress_text,
            status,
            style=style
        )
    
    console.print(table)


async def main():
    """Main execution function"""
    console.clear()
    console.print(Panel.fit(
        "🎮 Discord Quest Automator",
        style="bold blue",
        subtitle="Starting quest processing..."
    ))
    
    # Log startup to file
    logger.info("Discord Quest Automator started")
    
    async with aiohttp.ClientSession(
        base_url="https://discord.com/api/v10/",
        raise_for_status=True,
        timeout=aiohttp.ClientTimeout(total=60)
    ) as session:
        # Start heartbeat rotation
        asyncio.create_task(change_heartbeat_id(session))
        
        # Update build number
        try:
            raw_html = await (await session.get("/")).text()
            build_number_match = re.search(r''''BUILD_NUMBER":\s*"(\d+)''', raw_html)
            if build_number_match:
                SUPER_PROPERTIES["client_build_number"] = int(build_number_match.group(1))
                console.print(f"📦 Updated build number to: {build_number_match.group(1)}", style="dim")
            
            HEADERS["X-Super-Properties"] = base64_encode(dump_json(SUPER_PROPERTIES))
            session.headers.update(HEADERS)
        except Exception as e:
            console.print(f"⚠️  Failed to update build number: {e}", style="yellow")
            logger.warning(f"Failed to update build number: {e}")
        
        # Fetch quests
        save_path = Path("saved").expanduser()
        save_path.mkdir(parents=True, exist_ok=True)
        
        console.print("🔍 Fetching available quests...", style="dim")
        logger.info("Fetching available quests...")
        
        try:
            quests_response = DotMap(await (await session.get("quests/@me")).json())
        except Exception as e:
            console.print(f"❌ Failed to fetch quests: {e}", style="red bold")
            logger.error(f"Failed to fetch quests: {e}")
            return
        
        if quests_response.quest_enrollment_blocked_until:
            error_msg = (
                "❌ Blocked from doing quests until "
                f"{quests_response.quest_enrollment_blocked_until}"
            )
            console.print(error_msg, style="red bold")
            logger.error(error_msg)
            return
        
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
        
        # Process quests
        quests_with_state = [
            (quest, make_state(quest)) 
            for quest in filter(valid_quest, quests_response.quests)
        ]
        quests_with_state.sort(key=lambda v: v[1].type, reverse=True)
        
        if not quests_with_state:
            console.print("🎉 No quests to complete!", style="bold green")
            logger.info("No quests to complete")
            return
        
        # Display summary
        display_quest_summary(quests_with_state)
        console.print(f"\n📊 Found {len(quests_with_state)} quest(s) to process\n")
        logger.info(f"Found {len(quests_with_state)} quest(s) to process")
        
        # Create progress display
        with create_progress_display() as progress:
            # Create semaphore to limit concurrent quests
            semaphore = asyncio.Semaphore(1)  # Process 1 quests at a time
            
            async def process_quest(quest, state, task_id):
                """Process individual quest with error handling"""
                def update(task_type: str, done: int, total: int):
                    prev_value = progress.tasks[task_id].completed

                    while prev_value < done:
                        prev_value += 1
                        progress.update(task_id, completed=prev_value, total=total)
                        if done >= total:
                            progress.stop_task(task_id)
                            break

                        sleep(.01)
                
                quest_name = state.name[:30] + "..." if len(state.name) > 30 else state.name
                description = f"[{state.type.name}] {quest_name}"
                progress.start_task(task_id)
                progress.update(task_id, description=description)
                
                try:
                    await complete_quest(quest, session, update, semaphore)
                    progress.update(task_id, description=f"✅ {description}")
                    return True
                except Exception as e:
                    progress.update(
                        task_id,
                        description=f"❌ {description}",
                        style="red"
                    )
                    logger.error(f"Failed to process quest '{state.name}': {e}")
                    return False
            
            # Create tasks for all quests
            tasks = []
            for quest, state in quests_with_state:
                quest_name = state.name[:30] + "..." if len(state.name) > 30 else state.name
                task_id = progress.add_task(
                    f"[{state.type.name}] {quest_name}",
                    total=state.total,
                    completed=state.done,
                    start=False,
                )
                tasks.append(process_quest(quest, state, task_id))
            
            # Run all tasks
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Show summary
            successful = sum(1 for r in results if r is True)
            failed = sum(1 for r in results if r is False)
            
            console.print("\n" + "="*50)
            summary_msg = (
                f"🎯 Processing Complete!\n"
                f"✅ Successful: {successful}\n"
                f"❌ Failed: {failed}\n"
                f"📊 Total: {len(quests_with_state)}"
            )
            console.print(
                Panel.fit(
                    summary_msg,
                    style="green" if failed == 0 else "yellow"
                )
            )
            logger.info(f"Processing complete: {successful} successful, {failed} failed")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n👋 Process interrupted by user", style="yellow")
        logger.info("Process interrupted by user")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n💥 Critical error: {e}", style="red bold")
        logger.exception("Critical error in main")
        sys.exit(1)
