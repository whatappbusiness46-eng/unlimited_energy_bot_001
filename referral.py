import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import ContextTypes

from config import REFERRAL_REWARD

from database import (
    get_user,
    update_user,
    add_balance,
    add_activity,
)


logger = logging.getLogger(__name__)


# ============================================================
# HELPERS
# ============================================================

def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_user(user_id):
    try:
        return get_user(
            user_id,
            create=False,
        )
    except TypeError:
        return get_user(user_id)


def _get_bot_username(context):
    username = getattr(
        context.bot,
        "username",
        None,
    )

    if username:
        return str(username).lstrip("@")

    try:
        me = context.bot.get_me
        if callable(me):
            # Do not make a synchronous network call here.
            # The username should normally already be available.
            pass
    except Exception:
        pass

    return None


def _referral_link(context, user_id):
    username = _get_bot_username(context)

    if not username:
        return None

    return (
        f"https://t.me/{username}"
        f"?start=ref_{user_id}"
    )


def _home_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🏠 Home",
                    callback_data="home",
                )
            ]
        ]
    )


# ============================================================
# REFERRAL MENU
# ============================================================

def referral_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "🔗 Get Referral Link",
                callback_data="referral_link",
            )
        ],
        [
            InlineKeyboardButton(
                "📊 My Referrals",
                callback_data="referral_stats",
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="home",
            )
        ],
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


# ============================================================
# REFERRAL PAGE
# ============================================================

async def referral(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user

    if not user:
        return

    user_id = user.id
    db_user = _get_user(user_id)

    if not db_user:
        message = update.effective_message

        if message:
            await message.reply_text(
                "⚠️ User account not found.",
                reply_markup=_home_keyboard(),
            )

        return

    if (
        db_user.get("banned", False)
        or db_user.get("blacklisted", False)
    ):
        message = update.effective_message

        if message:
            await message.reply_text(
                "🚫 Your account is restricted.",
                reply_markup=_home_keyboard(),
            )

        return

    referrals = _safe_int(
        db_user.get("referrals", 0),
        0,
    )

    referral_earn = _safe_int(
        db_user.get("referral_earn", 0),
        0,
    )

    referral_link = _referral_link(
        context,
        user_id,
    )

    if referral_link:
        link_text = referral_link
    else:
        link_text = (
            "⚠️ Referral link is temporarily "
            "unavailable."
        )

    message = update.effective_message

    if not message:
        return

    await message.reply_text(
        "👥 **REFERRAL PROGRAM**\n\n"
        "🎁 Invite your friends and earn rewards!\n\n"
        f"💰 Reward per referral: "
        f"{REFERRAL_REWARD} Points\n\n"
        f"👥 Total Referrals: {referrals}\n"
        f"💵 Referral Earnings: "
        f"{referral_earn} Points\n\n"
        "🔗 Your Referral Link:\n"
        f"{link_text}\n\n"
        "📢 Share your link with your friends!",
        reply_markup=referral_menu(),
        parse_mode="Markdown",
    )


# ============================================================
# REFERRAL LINK CALLBACK
# ============================================================

async def referral_link_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if not query:
        return

    await query.answer()

    user = query.from_user

    if not user:
        return

    user_id = user.id
    db_user = _get_user(user_id)

    if not db_user:
        await query.edit_message_text(
            "⚠️ User account not found.",
            reply_markup=_home_keyboard(),
        )
        return

    if (
        db_user.get("banned", False)
        or db_user.get("blacklisted", False)
    ):
        await query.edit_message_text(
            "🚫 Your account is restricted.",
            reply_markup=_home_keyboard(),
        )
        return

    referral_link = _referral_link(
        context,
        user_id,
    )

    if not referral_link:
        await query.edit_message_text(
            "⚠️ Unable to generate your referral "
            "link right now.",
            reply_markup=referral_menu(),
        )
        return

    keyboard = [
        [
            InlineKeyboardButton(
                "📊 Referral Stats",
                callback_data="referral_stats",
            )
        ],
        [
            InlineKeyboardButton(
                "👥 Referral Menu",
                callback_data="refer",
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="home",
            )
        ],
    ]

    await query.edit_message_text(
        "🔗 **YOUR REFERRAL LINK**\n\n"
        f"`{referral_link}`\n\n"
        f"🎁 You earn "
        f"{REFERRAL_REWARD} Points "
        "for every valid referral.\n\n"
        "📢 Share this link with your friends!",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
        parse_mode="Markdown",
    )


# ============================================================
# REFERRAL STATISTICS
# ============================================================

async def referral_stats_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query

    if not query:
        return

    await query.answer()

    user = query.from_user

    if not user:
        return

    user_id = user.id
    db_user = _get_user(user_id)

    if not db_user:
        await query.edit_message_text(
            "⚠️ User account not found.",
            reply_markup=_home_keyboard(),
        )
        return

    if (
        db_user.get("banned", False)
        or db_user.get("blacklisted", False)
    ):
        await query.edit_message_text(
            "🚫 Your account is restricted.",
            reply_markup=_home_keyboard(),
        )
        return

    referrals = _safe_int(
        db_user.get("referrals", 0),
        0,
    )

    referral_earn = _safe_int(
        db_user.get("referral_earn", 0),
        0,
    )

    referred_by = db_user.get(
        "referred_by",
        None,
    )

    if referred_by:
        referred_text = (
            f"👤 Referred By: {referred_by}"
        )
    else:
        referred_text = (
            "👤 Referred By: None"
        )

    keyboard = [
        [
            InlineKeyboardButton(
                "🔗 Referral Link",
                callback_data="referral_link",
            )
        ],
        [
            InlineKeyboardButton(
                "👥 Referral Menu",
                callback_data="refer",
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 Home",
                callback_data="home",
            )
        ],
    ]

    await query.edit_message_text(
        "📊 **REFERRAL STATISTICS**\n\n"
        f"👥 Total Referrals: {referrals}\n"
        f"💰 Referral Earnings: "
        f"{referral_earn} Points\n\n"
        f"{referred_text}\n\n"
        f"🎁 Reward per referral: "
        f"{REFERRAL_REWARD} Points",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
        parse_mode="Markdown",
    )


# ============================================================
# PROCESS REFERRAL
# ============================================================

def process_referral(
    new_user_id,
    referral_id,
):
    new_user_id = _safe_int(
        new_user_id,
        0,
    )

    referral_id = _safe_int(
        referral_id,
        0,
    )

    # --------------------------------------------------------
    # INVALID REFERRAL
    # --------------------------------------------------------

    if (
        new_user_id <= 0
        or referral_id <= 0
    ):
        return False

    # --------------------------------------------------------
    # SELF REFERRAL BLOCK
    # --------------------------------------------------------

    if new_user_id == referral_id:
        logger.warning(
            "Self referral blocked | user=%s",
            new_user_id,
        )
        return False

    # --------------------------------------------------------
    # GET USERS
    # --------------------------------------------------------

    new_user = _get_user(
        new_user_id
    )

    referrer = _get_user(
        referral_id
    )

    # --------------------------------------------------------
    # MISSING USERS
    # --------------------------------------------------------

    if not new_user:
        logger.warning(
            "Referral failed: new user missing | "
            "user=%s",
            new_user_id,
        )
        return False

    if not referrer:
        logger.warning(
            "Referral failed: referrer missing | "
            "referrer=%s",
            referral_id,
        )
        return False

    # --------------------------------------------------------
    # RESTRICTED ACCOUNTS
    # --------------------------------------------------------

    if (
        new_user.get("banned", False)
        or new_user.get("blacklisted", False)
    ):
        return False

    if (
        referrer.get("banned", False)
        or referrer.get("blacklisted", False)
    ):
        return False

    # --------------------------------------------------------
    # ALREADY REFERRED
    # --------------------------------------------------------

    existing_referrer = new_user.get(
        "referred_by"
    )

    if existing_referrer is not None:
        logger.info(
            "Duplicate referral blocked | "
            "user=%s | existing_referrer=%s",
            new_user_id,
            existing_referrer,
        )
        return False

    # --------------------------------------------------------
    # VALIDATE REWARD
    # --------------------------------------------------------

    reward = _safe_int(
        REFERRAL_REWARD,
        0,
    )

    if reward <= 0:
        logger.error(
            "Invalid REFERRAL_REWARD=%s",
            REFERRAL_REWARD,
        )
        return False

    # --------------------------------------------------------
    # SAVE REFERRAL
    # --------------------------------------------------------

    try:
        updated = update_user(
            new_user_id,
            {
                "referred_by": referral_id,
            },
        )

        # Some database implementations return None
        # on successful update, so only explicit False
        # is treated as failure.
        if updated is False:
            return False

    except Exception:
        logger.exception(
            "Failed to save referral | "
            "new_user=%s | referrer=%s",
            new_user_id,
            referral_id,
        )
        return False

    # --------------------------------------------------------
    # REFERRER REWARD
    # --------------------------------------------------------

    try:
        balance_result = add_balance(
            referral_id,
            reward,
        )

        if balance_result is False:
            # Roll back the referral link if the balance
            # update explicitly failed.
            try:
                update_user(
                    new_user_id,
                    {
                        "referred_by": None,
                    },
                )
            except Exception:
                logger.exception(
                    "Referral rollback failed | user=%s",
                    new_user_id,
                )

            return False

    except Exception:
        logger.exception(
            "Failed to reward referrer | "
            "referrer=%s | reward=%s",
            referral_id,
            reward,
        )

        try:
            update_user(
                new_user_id,
                {
                    "referred_by": None,
                },
            )
        except Exception:
            logger.exception(
                "Referral rollback failed | user=%s",
                new_user_id,
            )

        return False

    # --------------------------------------------------------
    # UPDATE REFERRAL COUNT/EARNINGS
    # --------------------------------------------------------

    current_referrals = _safe_int(
        referrer.get("referrals", 0),
        0,
    )

    current_earn = _safe_int(
        referrer.get("referral_earn", 0),
        0,
    )

    try:
        updated = update_user(
            referral_id,
            {
                "referrals":
                    current_referrals + 1,
                "referral_earn":
                    current_earn + reward,
            },
        )

        if updated is False:
            logger.error(
                "Failed to update referral counters | "
                "referrer=%s",
                referral_id,
            )
            return False

    except Exception:
        logger.exception(
            "Failed to update referral counters | "
            "referrer=%s",
            referral_id,
        )
        return False

    # --------------------------------------------------------
    # ACTIVITY
    # --------------------------------------------------------

    try:
        add_activity(
            referral_id,
            "👥 Referral reward received",
            reward,
        )
    except Exception:
        logger.exception(
            "Failed to record referral activity | "
            "referrer=%s",
            referral_id,
        )

    logger.info(
        "Referral successful | "
        "new_user=%s | referrer=%s | reward=%s",
        new_user_id,
        referral_id,
        reward,
    )

    return True


# ============================================================
# HANDLER EXPORTS
# ============================================================

HANDLER_FUNCTIONS = {
    "referral": referral,
    "referral_link_callback":
        referral_link_callback,
    "referral_stats_callback":
        referral_stats_callback,
    "process_referral":
        process_referral,
}


__all__ = [
    "referral_menu",
    "referral",
    "referral_link_callback",
    "referral_stats_callback",
    "process_referral",
    "HANDLER_FUNCTIONS",
        ]
    
