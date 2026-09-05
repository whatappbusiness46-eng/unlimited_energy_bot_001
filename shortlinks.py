# ============================================================
# SHORTLINKS SYSTEM
# ============================================================

import logging
import secrets
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

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
    db,
)

logger = logging.getLogger(__name__)

SHORTLINKS: Dict[str, Dict[str, Any]] = {}
SHORTLINK_COLLECTION = db["shortlinks"]
TOKENS: Dict[str, Dict[str, Any]] = {}

DEFAULT_TOKEN_TTL = 3600
DEFAULT_COOLDOWN = 86400


def _now():
    return int(time.time())


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_user(user_id):
    try:
        return get_user(user_id, create=False)
    except TypeError:
        return get_user(user_id)


def _blocked(user):
    return bool(
        not user
        or user.get("banned", False)
        or user.get("blacklisted", False)
    )


def register_shortlink(
    shortlink_id: str,
    name: str,
    base_url: str,
    reward: int = 0,
    enabled: bool = True,
    cooldown: int = DEFAULT_COOLDOWN,
    token_ttl: int = DEFAULT_TOKEN_TTL,
):
    shortlink_id = str(shortlink_id).strip()
    reward = _safe_int(reward, 0)

    if not shortlink_id or not base_url or reward < 0:
        return False

    item = {
        "id": shortlink_id,
        "name": str(name or shortlink_id),
        "base_url": str(base_url),
        "reward": reward,
        "enabled": bool(enabled),
        "cooldown": max(0, _safe_int(cooldown, DEFAULT_COOLDOWN)),
        "token_ttl": max(60, _safe_int(token_ttl, DEFAULT_TOKEN_TTL)),
        "updated_at": _now(),
    }

    try:
        SHORTLINK_COLLECTION.create_index("id", unique=True, name="shortlink_id_unique")
        SHORTLINK_COLLECTION.update_one(
            {"id": shortlink_id},
            {"$set": item},
            upsert=True,
        )
    except Exception:
        logger.exception("Could not persist shortlink | id=%s", shortlink_id)
        return False

    SHORTLINKS[shortlink_id] = item
    return True


def get_shortlink(shortlink_id):
    key = str(shortlink_id)
    item = SHORTLINKS.get(key)
    if item:
        return dict(item)
    try:
        item = SHORTLINK_COLLECTION.find_one({"id": key}, {"_id": 0})
    except Exception:
        item = None
    if item:
        SHORTLINKS[key] = dict(item)
        return dict(item)
    return None


def get_shortlinks(include_disabled=False):
    try:
        query = {} if include_disabled else {"enabled": True}
        items = [dict(x) for x in SHORTLINK_COLLECTION.find(query, {"_id": 0}).sort("id", 1)]
        for item in items:
            SHORTLINKS[item["id"]] = item
        return items
    except Exception:
        return [
            dict(item)
            for item in SHORTLINKS.values()
            if include_disabled or item.get("enabled", True)
        ]


def set_shortlink_enabled(shortlink_id, enabled):
    key = str(shortlink_id)
    try:
        result = SHORTLINK_COLLECTION.update_one(
            {"id": key},
            {"$set": {"enabled": bool(enabled), "updated_at": _now()}},
        )
        if result.matched_count <= 0:
            return False
    except Exception:
        logger.exception("Could not update shortlink | id=%s", key)
        return False
    if key in SHORTLINKS:
        SHORTLINKS[key]["enabled"] = bool(enabled)
    return True


def delete_shortlink(shortlink_id):
    key = str(shortlink_id)
    try:
        result = SHORTLINK_COLLECTION.delete_one({"id": key})
    except Exception:
        logger.exception("Could not delete shortlink | id=%s", key)
        return False
    SHORTLINKS.pop(key, None)
    return result.deleted_count > 0


def _claims(user):
    value = user.get("shortlink_claims", {})
    return dict(value) if isinstance(value, dict) else {}


def shortlink_available(user_id, shortlink_id):
    user = _get_user(user_id)
    item = get_shortlink(shortlink_id)

    if _blocked(user) or not item or not item["enabled"]:
        return False

    claims = _claims(user)
    last = _safe_int(claims.get(str(shortlink_id), 0), 0)

    if last <= 0:
        return True

    cooldown = max(
        0,
        _safe_int(item.get("cooldown", DEFAULT_COOLDOWN), DEFAULT_COOLDOWN),
    )
    return _now() - last >= cooldown


def create_shortlink_token(
    user_id,
    shortlink_id,
):
    user = _get_user(user_id)
    item = get_shortlink(shortlink_id)

    if _blocked(user) or not item or not item["enabled"]:
        return None

    if not shortlink_available(user_id, shortlink_id):
        return None

    token = secrets.token_urlsafe(16)

    TOKENS[token] = {
        "user_id": user_id,
        "shortlink_id": str(shortlink_id),
        "created_at": _now(),
        "expires_at": _now() + item["token_ttl"],
        "used": False,
    }

    return token


def validate_shortlink_token(
    token,
    user_id=None,
    shortlink_id=None,
):
    token = str(token or "").strip()

    if not token:
        return False

    record = TOKENS.get(token)

    if not record:
        return False

    if record.get("used", False):
        return False

    if _safe_int(record.get("expires_at"), 0) <= _now():
        TOKENS.pop(token, None)
        return False

    if user_id is not None and record.get("user_id") != user_id:
        return False

    if (
        shortlink_id is not None
        and record.get("shortlink_id") != str(shortlink_id)
    ):
        return False

    return True


def build_shortlink_url(
    shortlink_id,
    token,
):
    item = get_shortlink(shortlink_id)

    if not item or not token:
        return None

    query = urlencode({
        "token": token,
    })

    separator = "&" if "?" in item["base_url"] else "?"

    return f"{item['base_url']}{separator}{query}"


def complete_shortlink(
    user_id,
    shortlink_id,
    token,
):
    item = get_shortlink(shortlink_id)

    if not item or not item["enabled"]:
        return False

    if not validate_shortlink_token(
        token,
        user_id=user_id,
        shortlink_id=shortlink_id,
    ):
        return False

    if not shortlink_available(
        user_id,
        shortlink_id,
    ):
        return False

    user = _get_user(user_id)

    if _blocked(user):
        return False

    claims = _claims(user)
    claims[str(shortlink_id)] = _now()

    try:
        result = update_user(
            user_id,
            {"shortlink_claims": claims},
        )
        if result is False:
            return False

        reward = _safe_int(
            item.get("reward", 0),
            0,
        )

        if reward > 0:
            result = add_balance(
                user_id,
                reward,
            )
            if result is False:
                return False

            try:
                add_activity(
                    user_id,
                    f"🔗 Shortlink completed: {item['name']}",
                    reward,
                )
            except Exception:
                logger.exception(
                    "Shortlink activity failed | user=%s link=%s",
                    user_id,
                    shortlink_id,
                )

        TOKENS[token]["used"] = True
        return True

    except Exception:
        logger.exception(
            "Shortlink completion failed | user=%s link=%s",
            user_id,
            shortlink_id,
        )
        return False


def shortlinks_menu(user_id=None):
    keyboard = []

    for item in get_shortlinks():
        available = (
            True
            if user_id is None
            else shortlink_available(user_id, item["id"])
        )

        label = (
            f"🔗 {item['name']}"
            if available
            else f"⏳ {item['name']}"
        )

        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"shortlink_{item['id']}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton("🏠 Home", callback_data="home")
    ])

    return InlineKeyboardMarkup(keyboard)


async def shortlinks_page(
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

    items = get_shortlinks()

    if not items:
        text = (
            "🔗 **SHORTLINKS**\n\n"
            "No shortlinks are available right now."
        )
    else:
        lines = [
            "🔗 **SHORTLINKS**",
            "",
            "Complete a shortlink to earn rewards:",
            "",
        ]

        for item in items:
            status = (
                "🟢 Available"
                if shortlink_available(user.id, item["id"])
                else "🔴 Cooldown"
            )
            lines.append(
                f"{status} — {item['name']} (+{item['reward']})"
            )

        text = "\n".join(lines)

    await message.reply_text(
        text,
        reply_markup=shortlinks_menu(user.id),
        parse_mode="Markdown",
    )


async def shortlink_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if not query:
        return

    await query.answer()

    data = str(query.data or "")

    if not data.startswith("shortlink_"):
        return

    shortlink_id = data[len("shortlink_"):]
    item = get_shortlink(shortlink_id)

    if not item:
        await query.edit_message_text(
            "⚠️ Shortlink not found.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Shortlinks",
                    callback_data="shortlinks",
                )],
                [InlineKeyboardButton(
                    "🏠 Home",
                    callback_data="home",
                )],
            ]),
        )
        return

    token = create_shortlink_token(
        query.from_user.id,
        shortlink_id,
    )

    if not token:
        await query.edit_message_text(
            "⏳ **SHORTLINK UNAVAILABLE**\n\n"
            "This shortlink is on cooldown or unavailable.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Shortlinks",
                    callback_data="shortlinks",
                )],
                [InlineKeyboardButton(
                    "🏠 Home",
                    callback_data="home",
                )],
            ]),
            parse_mode="Markdown",
        )
        return

    url = build_shortlink_url(
        shortlink_id,
        token,
    )

    if not url:
        await query.edit_message_text(
            "⚠️ Shortlink URL could not be generated."
        )
        return

    await query.edit_message_text(
        "🔗 **SHORTLINK**\n\n"
        f"📌 {item['name']}\n\n"
        f"💰 Reward: {item['reward']} Points\n\n"
        "Open the shortlink and complete it, then return "
        "to verify your reward.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🚀 Open Shortlink",
                url=url,
            )],
            [InlineKeyboardButton(
                "✅ Verify",
                callback_data=f"shortlink_verify_{shortlink_id}_{token}",
            )],
            [InlineKeyboardButton(
                "🏠 Home",
                callback_data="home",
            )],
        ]),
        parse_mode="Markdown",
    )


async def shortlink_verify_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if not query:
        return

    await query.answer()

    data = str(query.data or "")

    prefix = "shortlink_verify_"

    if not data.startswith(prefix):
        return

    payload = data[len(prefix):]

    try:
        shortlink_id, token = payload.split("_", 1)
    except ValueError:
        await query.edit_message_text(
            "⚠️ Invalid verification request."
        )
        return

    item = get_shortlink(shortlink_id)

    if not item:
        await query.edit_message_text(
            "⚠️ Shortlink not found."
        )
        return

    success = complete_shortlink(
        query.from_user.id,
        shortlink_id,
        token,
    )

    if success:
        text = (
            "🎉 **SHORTLINK COMPLETED!**\n\n"
            f"🔗 {item['name']}\n"
            f"💰 +{item['reward']} Points"
        )
    else:
        text = (
            "❌ **VERIFICATION FAILED**\n\n"
            "The token is invalid, expired, already used, "
            "or the shortlink is on cooldown."
        )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "⬅️ Shortlinks",
                callback_data="shortlinks",
            )],
            [InlineKeyboardButton(
                "🏠 Home",
                callback_data="home",
            )],
        ]),
        parse_mode="Markdown",
    )


HANDLER_FUNCTIONS = {
    "shortlinks": shortlinks_page,
    "shortlink_callback": shortlink_callback,
    "shortlink_verify_callback": shortlink_verify_callback,
}

__all__ = [
    "SHORTLINKS",
    "TOKENS",
    "register_shortlink",
    "get_shortlink",
    "get_shortlinks",
    "shortlink_available",
    "create_shortlink_token",
    "validate_shortlink_token",
    "build_shortlink_url",
    "complete_shortlink",
    "shortlinks_menu",
    "shortlinks_page",
    "shortlink_callback",
    "shortlink_verify_callback",
    "HANDLER_FUNCTIONS",
  ]
  
