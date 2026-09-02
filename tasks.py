# ============================================================
# TASKS SYSTEM
# ============================================================

import logging
import time
from typing import Any, Dict, Iterable, Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import ContextTypes

from database import (
    get_user,
    update_user,
    add_balance,
    add_activity,
)

logger = logging.getLogger(__name__)

TASKS: Dict[str, Dict[str, Any]] = {}
TASK_COOLDOWN = 86400
DEFAULT_REWARD = 0


def _now() -> int:
    return int(time.time())


def _safe_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_user(user_id):
    try:
        return get_user(user_id, create=False)
    except TypeError:
        return get_user(user_id)


def _blocked(user: Optional[dict]) -> bool:
    return bool(
        not user
        or user.get("banned", False)
        or user.get("blacklisted", False)
    )


def register_task(
    task_id: str,
    title: str,
    description: str = "",
    reward: int = DEFAULT_REWARD,
    url: Optional[str] = None,
    cooldown: int = TASK_COOLDOWN,
    enabled: bool = True,
) -> bool:
    task_id = str(task_id).strip()
    reward = _safe_int(reward, 0)
    cooldown = max(0, _safe_int(cooldown, TASK_COOLDOWN))

    if not task_id or reward < 0:
        return False

    TASKS[task_id] = {
        "id": task_id,
        "title": str(title or task_id),
        "description": str(description or ""),
        "reward": reward,
        "url": url,
        "cooldown": cooldown,
        "enabled": bool(enabled),
    }
    return True


def get_tasks(include_disabled: bool = False):
    return [
        dict(task)
        for task in TASKS.values()
        if include_disabled or task.get("enabled", True)
    ]


def get_task(task_id: str):
    task = TASKS.get(str(task_id))
    return dict(task) if task else None


def _completed_map(user: dict) -> dict:
    value = user.get("completed_tasks", {})
    return dict(value) if isinstance(value, dict) else {}


def task_available(user_id, task_id: str) -> bool:
    user = _get_user(user_id)
    task = get_task(task_id)

    if _blocked(user) or not task or not task["enabled"]:
        return False

    completed = _completed_map(user)
    last = _safe_int(completed.get(task_id, 0), 0)

    if last <= 0:
        return True

    cooldown = max(0, _safe_int(task.get("cooldown", 0), 0))
    return _now() - last >= cooldown


def complete_task(user_id, task_id: str) -> bool:
    user = _get_user(user_id)
    task = get_task(task_id)

    if _blocked(user) or not task or not task["enabled"]:
        return False

    if not task_available(user_id, task_id):
        return False

    reward = _safe_int(task.get("reward", 0), 0)
    completed = _completed_map(user)
    completed[str(task_id)] = _now()

    try:
        result = update_user(
            user_id,
            {"completed_tasks": completed},
        )
        if result is False:
            return False

        if reward > 0:
            result = add_balance(user_id, reward)
            if result is False:
                return False

            try:
                add_activity(
                    user_id,
                    f"✅ Task completed: {task['title']}",
                    reward,
                )
            except Exception:
                logger.exception(
                    "Task activity failed | user=%s task=%s",
                    user_id,
                    task_id,
                )

        return True

    except Exception:
        logger.exception(
            "Task completion failed | user=%s task=%s",
            user_id,
            task_id,
        )
        return False


def tasks_menu(user_id=None):
    keyboard = []

    for task in get_tasks():
        task_id = task["id"]
        label = f"🎯 {task['title']}"
        if user_id is not None and not task_available(user_id, task_id):
            label = f"✅ {task['title']}"

        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"task_{task_id}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton("🏠 Home", callback_data="home")
    ])
    return InlineKeyboardMarkup(keyboard)


async def tasks_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    message = update.effective_message
    if not user or not message:
        return

    db_user = _get_user(user.id)
    if _blocked(db_user):
        await message.reply_text("🚫 Your account is restricted.")
        return

    task_list = get_tasks()

    if not task_list:
        text = "🎯 **TASKS**\n\nNo tasks are available right now."
    else:
        lines = ["🎯 **TASKS**", "", "Complete tasks to earn rewards:", ""]
        for task in task_list:
            status = "🟢 Available" if task_available(user.id, task["id"]) else "🔴 Cooldown"
            lines.append(
                f"{status} — {task['title']} (+{task['reward']})"
            )
        text = "\n".join(lines)

    await message.reply_text(
        text,
        reply_markup=tasks_menu(user.id),
        parse_mode="Markdown",
    )


async def task_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    if not query:
        return

    await query.answer()

    user = query.from_user
    data = str(query.data or "")

    if not data.startswith("task_"):
        return

    task_id = data[5:]
    task = get_task(task_id)

    if not task:
        await query.edit_message_text(
            "⚠️ Task not found.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Tasks", callback_data="tasks")],
                [InlineKeyboardButton("🏠 Home", callback_data="home")],
            ]),
        )
        return

    if task.get("url"):
        keyboard = [
            [InlineKeyboardButton("🚀 Open Task", url=task["url"])],
            [InlineKeyboardButton(
                "✅ Verify Task",
                callback_data=f"task_complete_{task_id}",
            )],
            [InlineKeyboardButton("🏠 Home", callback_data="home")],
        ]
        text = (
            f"🎯 **{task['title']}**\n\n"
            f"{task['description']}\n\n"
            f"💰 Reward: {task['reward']} Points"
        )
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    success = complete_task(user.id, task_id)

    if success:
        text = (
            "🎉 **TASK COMPLETED!**\n\n"
            f"🎯 {task['title']}\n"
            f"💰 Reward: {task['reward']} Points"
        )
    else:
        text = (
            "⚠️ **TASK NOT COMPLETED**\n\n"
            "The task may be unavailable or still on cooldown."
        )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Tasks", callback_data="tasks")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")],
        ]),
        parse_mode="Markdown",
    )


async def task_complete_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    if not query:
        return

    await query.answer()

    data = str(query.data or "")
    if not data.startswith("task_complete_"):
        return

    task_id = data[len("task_complete_"):]
    task = get_task(task_id)

    if not task:
        await query.edit_message_text("⚠️ Task not found.")
        return

    success = complete_task(
        query.from_user.id,
        task_id,
    )

    if success:
        text = (
            "🎉 **Verified!**\n\n"
            f"🎯 {task['title']}\n"
            f"💰 +{task['reward']} Points"
        )
    else:
        text = (
            "❌ **Verification failed**\n\n"
            "The task is already completed or unavailable."
        )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Tasks", callback_data="tasks")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")],
        ]),
        parse_mode="Markdown",
    )


HANDLER_FUNCTIONS = {
    "tasks": tasks_page,
    "task_callback": task_callback,
    "task_complete_callback": task_complete_callback,
}

__all__ = [
    "TASKS",
    "TASK_COOLDOWN",
    "register_task",
    "get_tasks",
    "get_task",
    "task_available",
    "complete_task",
    "tasks_menu",
    "tasks_page",
    "task_callback",
    "task_complete_callback",
    "HANDLER_FUNCTIONS",
  ]
      
