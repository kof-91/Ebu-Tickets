import asyncio
import html
import logging
import os

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ChatMemberStatus, ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
)
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH_USERS = os.path.join(BASE_DIR, "users.db")
DB_PATH_TICKETS = os.path.join(BASE_DIR, "tickets.db")

MAX_DESCRIPTION_LEN = 1500
MAX_REPLY_LEN = 3000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("ticket_bot")

router = Router()

CHANNELS = {
    "SOZDATEL V.2 🥭": (
        "@sozdatelebumangoofficial",
        "https://t.me/sozdatelebumangoofficial",
    ),
    "Канал": (
        "@pidorasiofficial",
        "https://t.me/pidorasiofficial",
    ),
}

BTN_ANON = "😷 АНОНИМНО"
BTN_NOT_ANON = "💎 НЕ АНОНИМНО"

BTN_NO_PHOTO = "нет"

def esc(text: str | None) -> str:
    return html.escape(str(text or ""), quote=False)


#ИДЕНТИФИКАТОР ПЕЧАТАНИЯ
async def typing(bot: Bot, chat_id: int):
    try:
        await bot.send_chat_action(
            chat_id=chat_id,
            action=ChatAction.TYPING,
        )
    except TelegramAPIError:
        pass

async def answer_typing(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup=None,
):
    await typing(bot, chat_id)

    return await bot.send_message(
        chat_id,
        text,
        reply_markup=reply_markup,
    )

def title(text: str) -> str:
    return f"<blockquote><b>{text}</b></blockquote>"


def error(text: str) -> str:
    return f"{title('❌ ОШИБКА ❌')}\n{text}"


def success(text: str) -> str:
    return f"{title('✅ ГОТОВО ✅')}\n{text}"


def info(text: str) -> str:
    return f"{title('ℹ️ ИНФО ℹ️')}\n{text}"


def ticket_status(status: str) -> tuple[str, str]:
    if status == "closed":
        return "🟢", "РАССМОТРЕН"

    return "🔴", "ОЖИДАЕТ"


def user_display(user, anonymous: bool) -> str:
    if anonymous:
        return "😷 <b>АНОНИМ</b>"

    if user.username:
        return f"👤 @{esc(user.username)}"

    return f"👤 {esc(user.full_name)}"


keyboard_confirm = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ СОГЛАСЕН",
                callback_data="confirm",
                style="success",
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ ОТМЕНА",
                callback_data="cancel_confirm",
                style="danger",
            )
        ],
    ]
)


def channels_keyboard() -> InlineKeyboardMarkup:
    rows = []

    for name, (_, url) in CHANNELS.items():
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📢 {name}",
                    url=url,
                    style="primary",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="🔄 ПРОВЕРИТЬ ПОДПИСКИ",
                callback_data="check_subs",
                style="success",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


keyboard_type = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(
                text=BTN_ANON,
                style="success",
            ),
            KeyboardButton(
                text=BTN_NOT_ANON,
                style="primary",
            ),
        ]
    ],
    resize_keyboard=True,
    is_persistent=False,
)


def reply_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 ОТВЕТИТЬ",
                    callback_data=f"reply_{ticket_id}",
                    style="success",
                ),
                InlineKeyboardButton(
                    text="🔴 ЗАКРЫТЬ",
                    callback_data=f"close_{ticket_id}",
                    style="danger",
                ),
            ]
        ]
    )


def admin_ticket_kb(ticket_id: int, status: str) -> InlineKeyboardMarkup:
    if status == "closed":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🟢 ТИКЕТ ЗАКРЫТ",
                        callback_data="noop",
                        style="success",
                    )
                ]
            ]
        )

    return reply_kb(ticket_id)

def ticket_text(
    ticket_id: int,
    anonymous: bool,
    user,
    description: str,
) -> str:
    sender = user_display(user, anonymous)

    return (
        f"{title(f'🎟 ТИКЕТ #{ticket_id}')}\n\n"
        f"<b>ОТ:</b> {sender}\n\n"
        f"<b>СООБЩЕНИЕ:</b>\n"
        f"<blockquote>{esc(description)}</blockquote>"
    )


def ticket_admin_text(
    ticket_id: int,
    username: str | None,
    description: str,
    anonymous: bool,
    status: str,
) -> str:
    if anonymous:
        sender = "😷 <b>АНОНИМ</b>"
    elif username:
        sender = f"👤 @{esc(username)}"
    else:
        sender = f"👤 БЕЗ USERNAME"

    icon, status_text = ticket_status(status)

    return (
        f"{title(f'🎟 ТИКЕТ #{ticket_id}')}\n\n"
        f"<b>СТАТУС:</b> {icon} {status_text}\n"
        f"<b>ОТ:</b> {sender}\n\n"
        f"<b>СООБЩЕНИЕ:</b>\n"
        f"<blockquote>{esc(description)}</blockquote>"
    )

async def send_card(
    bot: Bot,
    chat_id: int,
    text: str,
    photo_id: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
):

    if photo_id:
        if len(text) <= 1024:
            return await bot.send_photo(
                chat_id=chat_id,
                photo=photo_id,
                caption=text,
                reply_markup=reply_markup,
            )

        await bot.send_photo(
            chat_id=chat_id,
            photo=photo_id,
        )

    return await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
    )

async def init_users_db():
    async with aiosqlite.connect(DB_PATH_USERS) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS confirmed_users (
                user_id INTEGER PRIMARY KEY
            )
            """
        )
        await db.commit()


async def is_user_confirmed(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH_USERS) as db:
        async with db.execute(
            "SELECT 1 FROM confirmed_users WHERE user_id = ?",
            (user_id,),
        ) as cur:
            return await cur.fetchone() is not None


async def add_confirmed_user(user_id: int):
    async with aiosqlite.connect(DB_PATH_USERS) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO confirmed_users (user_id)
            VALUES (?)
            """,
            (user_id,),
        )
        await db.commit()


async def init_tickets_db():
    async with aiosqlite.connect(DB_PATH_TICKETS) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                description TEXT,
                photo_id TEXT,
                anonymous INTEGER,
                status TEXT
            )
            """
        )
        await db.commit()


async def create_ticket(
    user_id,
    username,
    description,
    photo_id,
    anonymous: bool,
) -> int:
    async with aiosqlite.connect(DB_PATH_TICKETS) as db:
        cur = await db.execute(
            """
            INSERT INTO tickets
            (
                user_id,
                username,
                description,
                photo_id,
                anonymous,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                description,
                photo_id,
                int(anonymous),
                "open",
            ),
        )

        await db.commit()

        return cur.lastrowid


async def get_ticket(ticket_id: int):
    async with aiosqlite.connect(DB_PATH_TICKETS) as db:
        async with db.execute(
            """
            SELECT
                user_id,
                description,
                status
            FROM tickets
            WHERE id = ?
            """,
            (ticket_id,),
        ) as cur:
            return await cur.fetchone()


async def close_ticket(ticket_id: int):
    async with aiosqlite.connect(DB_PATH_TICKETS) as db:
        await db.execute(
            """
            UPDATE tickets
            SET status = 'closed'
            WHERE id = ?
            """,
            (ticket_id,),
        )

        await db.commit()

class TicketForm(StatesGroup):
    choosing_type = State()
    waiting_for_description = State()
    waiting_for_photo = State()


class ReplyForm(StatesGroup):
    waiting_for_reply = State()


@router.message(Command("cancel"), StateFilter("*"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()

    await answer_typing(
        message.bot,
        message.chat.id,
        error("ДЕЙСТВИЕ ОТМЕНЕНО!"),
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(Command("start"))
async def send_welcome(message: Message, state: FSMContext):
    await state.clear()

    if await is_user_confirmed(message.from_user.id):
        await answer_typing(
            message.bot,
            message.chat.id,
            error("ТЫ УЖЕ ПОДТВЕРЖДЕН!")
        )
        return

    text = (
        f"{title('🎟 ЕБУ ТИКЕТЫ')}\n"
        "<b>РЕГИСТРАЦИЯ</b>\n\n"
        "ТИКЕТНАЯ СИСТЕМА ДЛЯ ОБРАЩЕНИЙ К АДМИНИСТРАТОРАМ БОТА @EBU_MANGU_BOT\n"
        "<b>👇ЖМИ НА КНОПКУ НИЖЕ ЧТОБЫ ПРОДОЛЖИТЬ👇</b>"
    )

    await answer_typing(
        message.bot,
        message.chat.id,
        text,
        reply_markup=keyboard_confirm,
    )


# ============================================================
# CONFIRM
# ============================================================

@router.callback_query(F.data == "cancel_confirm")
async def cancel_confirm(callback: CallbackQuery):

    if callback.message:
        await callback.message.edit_text(
            error("РЕГИСТРАЦИЯ ОТМЕНЕНА!"),
        )


@router.callback_query(F.data == "confirm")
async def process_confirm(callback: CallbackQuery):

    await callback.message.answer(
        (
            f"{title('📛 НЕ ТАК БЫСТРО')}\n"
            "<b>СНАЧАЛА ПОДПИШИСЬ НА КАНАЛЫ СНИЗУ👇</b>"
        ),
        reply_markup=channels_keyboard(),
    )

@router.callback_query(F.data == "check_subs")
async def check_subscription(
    callback: CallbackQuery,
    bot: Bot,
):
    user_id = callback.from_user.id

    not_subscribed = []
    check_errors = []

    for name, (channel, _) in CHANNELS.items():
        try:
            member = await bot.get_chat_member(
                channel,
                user_id,
            )

        except TelegramAPIError as e:
            logger.warning(
                "ОШИБКА ПРОВЕРКИ %s: %s",
                channel,
                e,
            )

            check_errors.append(name)
            continue

        if member.status in (
            ChatMemberStatus.LEFT,
            ChatMemberStatus.KICKED,
        ):
            not_subscribed.append(name)

    if check_errors:
        await callback.message.answer(
            error("НЕ УДАЛОСЬ ПРОВЕРИТЬ ПОДПИСКИ!"),
            reply_markup=channels_keyboard(),
        )
        return

    if not_subscribed:
        channels = "\n".join(
            f"• <b>{esc(name)}</b>"
            for name in not_subscribed
        )

        await callback.message.answer(
            (
                f"{title('❌ ОШИБКА ❌')}\n\n"
                "ВЫ НЕ ПОДПИСАНЫ НА СЛЕДУЮЩИЕ КАНАЛЫ:"
                f"{channels}\n\n"
            ),
            reply_markup=channels_keyboard(),
        )
        return

    await add_confirmed_user(user_id)

    await callback.message.answer(
        (
            f"{title('🟢 ДОБРО ПОЖАЛОВАТЬ 🟢')}\n\n"
            "УСПЕШНАЯ РЕГИСТРАЦИЯ!\n"
            "<b>/ticket</b> - СОЗДАТЬ ТИКЕТ\n"
            "<b>/mytickets</b> - МОИ ТИКЕТЫ"
        )
    )

@router.message(Command("ticket"))
async def start_ticket(
    message: Message,
    state: FSMContext,
):
    await state.clear()

    if not await is_user_confirmed(message.from_user.id):
        await answer_typing(
            message.bot,
            message.chat.id,
            error(
                "ТЫ НЕ ПОДТВЕРЖДЕН!\nПИШИ /start"
            ),
        )
        return

    await answer_typing(
        message.bot,
        message.chat.id,
        (
            f"{title('🎟 НОВЫЙ ТИКЕТ')}\n\n"
            "😷 АНОНИМНО - СКРЫТЬ ИМЯ\n"
            "💎 НЕ АНОНИМНО - РАСКРЫТЬ ИМЯ"
        ),
        reply_markup=keyboard_type,
    )

    await state.set_state(TicketForm.choosing_type)

@router.message(
    TicketForm.choosing_type,
    F.text.in_({BTN_ANON, BTN_NOT_ANON}),
)
async def choose_type(
    message: Message,
    state: FSMContext,
):
    anonymous = message.text == BTN_ANON

    await state.update_data(
        anonymous=anonymous,
    )

    await answer_typing(
        message.bot,
        message.chat.id,
        (
            f"{title('📝 ОПИШИТЕ ПРОБЛЕМУ')}\n\n"
            f"{'😷 АНОНИМНЫЙ ТИКЕТ' if anonymous else '💎 НЕ АНОНИМНО'}\n"
            f"МАКСИМУМ <b>{MAX_DESCRIPTION_LEN}</b> СИМВОЛОВ"
        ),
        reply_markup=ReplyKeyboardRemove(),
    )

    await state.set_state(
        TicketForm.waiting_for_description
    )


@router.message(TicketForm.choosing_type)
async def choose_type_invalid(message: Message):
    await message.answer(
        error("ВЫБЕРИ ОДНУ ИЗ КНОПОК 👇"),
        reply_markup=keyboard_type,
    )

@router.message(
    TicketForm.waiting_for_description,
    F.text,
)
async def get_description(
    message: Message,
    state: FSMContext,
):
    if len(message.text) > MAX_DESCRIPTION_LEN:
        await message.answer(
            error(
                f"СЛИШКОМ ДЛИННО!\n"
                f"ЛИМИТ: <b>{MAX_DESCRIPTION_LEN}</b> СИМВОЛОВ"
            )
        )
        return

    await state.update_data(
        description=message.text.strip()
    )

    await answer_typing(
        message.bot,
        message.chat.id,
        (
            f"{title('📸 ФОТО 📸')}\n\n"
            "ПРИКРЕПИ ФОТО К СВОЕМУ ОБРАЩЕНИЮ\n"
            "ИЛИ НАПИШИ <b>«нет»</b>"
        ),
    )

    await state.set_state(
        TicketForm.waiting_for_photo
    )


@router.message(TicketForm.waiting_for_description)
async def get_description_invalid(message: Message):
    await message.answer(
        error("ТЕКСТ НЕ ОБНАРУЖЕН📝")
    )

@router.message(
    TicketForm.waiting_for_photo,
    F.photo | F.text,
)
async def get_photo_or_skip(
    message: Message,
    state: FSMContext,
    bot: Bot,
):
    photo_id = None

    if message.photo:
        photo_id = message.photo[-1].file_id

    elif (
        not message.text
        or message.text.strip().lower() != BTN_NO_PHOTO
    ):
        await message.answer(
            error(
                "ПРИКРЕПИ ФОТО 📸\n"
                "ИЛИ НАПИШИ <b>«нет»</b>."
            )
        )
        return

    data = await state.get_data()

    anonymous = data["anonymous"]
    description = data["description"]

    ticket_id = await create_ticket(
        user_id=message.from_user.id,
        username=message.from_user.username,
        description=description,
        photo_id=photo_id,
        anonymous=anonymous,
    )

    text = ticket_text(
        ticket_id=ticket_id,
        anonymous=anonymous,
        user=message.from_user,
        description=description,
    )

    try:
        await send_card(
            bot=bot,
            chat_id=ADMIN_ID,
            text=text,
            photo_id=photo_id,
            reply_markup=reply_kb(ticket_id),
        )

    except TelegramAPIError as e:
        logger.error(
            "НЕУДАЛОСЬ ОТПРАВИТЬ ТИКЕТ #%s АДМИНУ: %s",
            ticket_id,
            e,
        )

        await message.answer(
            error(
                "ТИКЕТ СОЗДАН НО НЕ УДАЛОСЬ"
                "ДОСТАВИТЬ ЕГО АДМИНУ!"
            )
        )

        await state.clear()
        return

    await answer_typing(
        bot,
        message.chat.id,
        (
            f"{title('🟢 ТИКЕТ ОТПРАВЛЕН')}\n\n"
            f"<b>НОМЕР:</b> #{ticket_id}\n"
            "ОЖИДАЙТЕ ОТВЕТ В ТЕЧЕНИИ 24 ЧАСОВ"
        ),
    )

    await state.clear()


@router.message(TicketForm.waiting_for_photo)
async def get_photo_invalid(message: Message):
    await message.answer(
        error(
            "НУЖНО ФОТО 📸\n"
            "ИЛИ НАПИШИ <b>«нет»</b>."
        )
    )

@router.message(Command("mytickets"))
async def my_tickets(message: Message):
    if not await is_user_confirmed(message.from_user.id):
        await message.answer(
            error(
                "ТЫ НЕ ПОДТВЕРЖДЁН!\n"
                "ЖМИ <b>/start</b>."
            )
        )
        return

    async with aiosqlite.connect(DB_PATH_TICKETS) as db:
        async with db.execute(
            """
            SELECT
                id,
                description,
                status
            FROM tickets
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 5
            """,
            (message.from_user.id,),
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await message.answer(
            info("У ТЕБЯ ПОКА НЕТ ТИКЕТОВ 📭")
        )
        return

    cards = []

    for ticket_id, description, status in rows:
        icon, status_text = ticket_status(status)

        short = description[:80]

        if len(description) > 80:
            short += "…"

        cards.append(
            (
                f"<b>#{ticket_id}</b>  "
                f"{icon} <b>{status_text}</b>\n"
                f"<blockquote>{esc(short)}</blockquote>"
            )
        )

    await message.answer(
        (
            f"{title('🎟 МОИ ТИКЕТЫ')}\n\n"
            + "\n\n".join(cards)
        )
    )

@router.message(
    Command("tickets"),
    F.from_user.id == ADMIN_ID,
)
async def admin_open_tickets(
    message: Message,
    bot: Bot,
):
    async with aiosqlite.connect(DB_PATH_TICKETS) as db:
        async with db.execute(
            """
            SELECT
                id,
                username,
                description,
                photo_id,
                anonymous,
                status
            FROM tickets
            WHERE status = 'open'
            ORDER BY id DESC
            LIMIT 10
            """
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await message.answer(
            success("ОТКРЫТЫХ ТИКЕТОВ НЕТ 🧘")
        )
        return

    await typing(bot, message.chat.id)

    for (
        ticket_id,
        username,
        description,
        photo_id,
        anonymous,
        status,
    ) in rows:

        text = ticket_admin_text(
            ticket_id=ticket_id,
            username=username,
            description=description,
            anonymous=bool(anonymous),
            status=status,
        )

        await send_card(
            bot=bot,
            chat_id=ADMIN_ID,
            text=text,
            photo_id=photo_id,
            reply_markup=admin_ticket_kb(
                ticket_id,
                status,
            ),
        )

        await asyncio.sleep(0.15)

@router.callback_query(
    F.data.startswith("reply_"),
    F.from_user.id == ADMIN_ID,
)
async def start_reply(
    callback: CallbackQuery,
    state: FSMContext,
):
    ticket_id = int(
        callback.data.split("_")[1]
    )

    ticket = await get_ticket(ticket_id)

    if not ticket:
        await callback.answer(
            "ТИКЕТ НЕ НАЙДЕН",
            show_alert=True,
        )
        return

    if ticket[2] == "closed":
        await callback.answer(
            "ТИКЕТ УЖЕ ЗАКРЫТ",
            show_alert=True,
        )
        return

    await state.update_data(
        ticket_id=ticket_id
    )

    await callback.answer("ПИШИ ОТВЕТ 💬")

    await callback.message.answer(
        (
            f"{title(f'💬 ОТВЕТ НА #{ticket_id}')}\n\n"
            "ОТПРАВЬТЕ ТЕКСТ ИЛИ ФОТО С ОПИСАНИЕМ\n"
            f"ЛИМИТ ТЕКСТА: <b>{MAX_REPLY_LEN}</b>."
        )
    )

    await state.set_state(
        ReplyForm.waiting_for_reply
    )

@router.callback_query(
    F.data.startswith("close_"),
    F.from_user.id == ADMIN_ID,
)
async def admin_close_ticket(
    callback: CallbackQuery,
):
    ticket_id = int(
        callback.data.split("_")[1]
    )

    ticket = await get_ticket(ticket_id)

    if not ticket:
        await callback.answer(
            "ТИКЕТ НЕ НАЙДЕН",
            show_alert=True,
        )
        return

    if ticket[2] == "closed":
        await callback.answer(
            "УЖЕ ЗАКРЫТ",
            show_alert=True,
        )
        return

    await close_ticket(ticket_id)

    await callback.answer(
        "ТИКЕТ ЗАКРЫТ 🟢"
    )

    try:
        await callback.message.edit_reply_markup(
            reply_markup=admin_ticket_kb(
                ticket_id,
                "closed",
            )
        )
    except TelegramAPIError:
        pass

@router.message(
    ReplyForm.waiting_for_reply,
    F.text | F.photo,
)
async def send_reply(
    message: Message,
    state: FSMContext,
    bot: Bot,
):
    data = await state.get_data()

    ticket_id = data["ticket_id"]

    ticket = await get_ticket(ticket_id)

    if not ticket:
        await message.answer(
            error("ТИКЕТ НЕ НАЙДЕН.")
        )
        await state.clear()
        return

    user_id, user_question, status = ticket

    if status == "closed":
        await message.answer(
            error("ТИКЕТ УЖЕ ЗАКРЫТ.")
        )
        await state.clear()
        return

    if message.photo:
        photo_id = message.photo[-1].file_id
        answer_text = message.caption or ""

    else:
        photo_id = None
        answer_text = message.text or ""

    if len(answer_text) > MAX_REPLY_LEN:
        await message.answer(
            error(
                f"ОТВЕТ СЛИШКОМ ДЛИННЫЙ.\n\n"
                f"ЛИМИТ: <b>{MAX_REPLY_LEN}</b>."
            )
        )
        return

    text = (
        f"{title(f'🟢 ТИКЕТ #{ticket_id} РАССМОТРЕН')}\n"
        f"<b>ТВОЙ ВОПРОС:</b>\n"
        f"<blockquote>{esc(user_question)}</blockquote>\n\n"
        f"<b>ОТВЕТ АДМИНА:</b>\n"
        f"<blockquote>{esc(answer_text)}</blockquote>"
    )

    try:
        await send_card(
            bot=bot,
            chat_id=user_id,
            text=text,
            photo_id=photo_id,
        )

    except TelegramForbiddenError:
        await message.answer(
            error(
                "НЕ УДАЛОСЬ ДОСТАВИТЬ ОТВЕТ\n"
                "ПОЛЬЗОВАТЕЛЬ ЗАБЛОКИРОВАЛ БОТА!"
            )
        )

        await state.clear()
        return

    except TelegramAPIError as e:
        logger.error(
            "ОШИБКА ОТВЕТА ПО ТИКЕТУ #%s: %s",
            ticket_id,
            e,
        )

        await message.answer(
            error(
                "ОШИБКА ОТПРАВКИ\n"
                "ПОПРОБУЙ ЕЩЁ РАЗ"
            )
        )
        return

    await close_ticket(ticket_id)

    await message.answer(
        success(
            f"ОТВЕТ ПО ТИКЕТУ #{ticket_id} ОТПРАВЛЕН"
        )
    )

    await state.clear()

@router.message(
    ReplyForm.waiting_for_reply,
)
async def send_reply_invalid(message: Message):
    await message.answer(
        error(
            "ТОЛЬКО ТЕКСТ ИЛИ ФОТО 📸"
        )
    )


@router.message(F.text)
async def fallback_text(message: Message):
    await message.answer(
        error(
            "НЕИЗВЕСТНАЯ КОМАНДА!\n\n"
            "<blockquote>ДОСТУПНЫЕ КОМАНДЫ:</blockquote>\n"
            "<b>/ticket</b> - СОЗДАТЬ ТИКЕТ\n"
            "<b>/mytickets</b> - МОИ ТИКЕТЫ"
        )
    )

async def setup_commands(bot: Bot):
    await bot.set_my_commands(
        [
            BotCommand(
                command="ticket",
                description="СОЗДАТЬ ТИКЕТ🎟🎟🎟",
            ),
            BotCommand(
                command="mytickets",
                description="МОИ ТЕКУЩИЕ ТИКЕТЫ🎟🎟🎟",
            ),
            BotCommand(
                command="cancel",
                description="ОТМЕНИТЬ ДЕЙСТВИЕ❌❌❌",
            ),
        ]
    )

    #КОМАНДЫ ДЛЯ АДМИНА
    await bot.set_my_commands(
        [
            BotCommand(
                command="ticket",
                description="СОЗДАТЬ ТИКЕТ🎟🎟🎟",
            ),
            BotCommand(
                command="mytickets",
                description="МОИ ТИКЕТЫ🎟🎟🎟",
            ),
            BotCommand(
                command="tickets",
                description="ОТКРЫТЫЕ ТИКЕТЫ🎟🎟🎟",
            ),
            BotCommand(
                command="cancel",
                description="ОТМЕНИТЬ ДЕЙСТВИЕ❌❌❌",
            ),
        ],
        scope={"type": "chat", "chat_id": ADMIN_ID},
    )

async def main():
    if not TOKEN:
        raise RuntimeError(
            "НЕ ЗАДАН ТОКЕН БОТА!"
        )

    await init_users_db()
    await init_tickets_db()

    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
        ),
    )

    await setup_commands(bot)

    dp = Dispatcher(
        storage=MemoryStorage()
    )

    dp.include_router(router)

    await bot.delete_webhook(
        drop_pending_updates=True
    )

    logger.info("УСПЕШНЫЙ ЗАПУСК🟢")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
