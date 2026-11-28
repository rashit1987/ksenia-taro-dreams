import asyncio
import logging
import os
import random
import re
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LabeledPrice,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
)
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
VSEGPT_API_KEY = os.getenv("VSEGPT_API_KEY", "").strip()
DREAMCATCHERS_CHANNEL_URL = os.getenv(
    "DREAMCATCHERS_CHANNEL_URL",
    "https://t.me" + "kata_nakata",
).strip()

ADMIN_IDS = {1795533772, 1273001338, 610828745}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
ai_client = AsyncOpenAI(api_key=VSEGPT_API_KEY, base_url="https://" + "api.vsegpt.ru/v1", timeout=60.0)

conn = sqlite3.connect("taro_ksenia.db")
cursor = conn.cursor()
cursor.execute(
    "CREATE TABLE IF NOT EXISTS users ("
    "user_id INTEGER PRIMARY KEY, "
    "username TEXT, "
    "last_free_date TEXT, "
    "paid_readings INTEGER DEFAULT 1)"
)
try:
    cursor.execute("ALTER TABLE users ADD COLUMN paid_readings INTEGER DEFAULT 1")
except Exception:
    pass
conn.commit()

TAROT_DECKS = [
    "Классическая колода Райдера-Уэйта (тёплый символизм и архетипы)",
    "Мистическое Таро Ночного Леса (глубокая интуиция и природные образы)",
    "Неоновое Кибер-Таро будущего (острые, современные и прямые трактовки)",
    "Таро Светлого Провидца (мягкая психология и поддержка)",
    "Готическое Таро Теней (честный разбор скрытых мотивов)",
    "Таро Золотого Арт-Нуво (эстетика, чувства и гармония)",
    "Таро Древних Славянских Снов (мудрость предков и знаки судьбы)",
]


def get_random_deck() -> str:
    return random.choice(TAROT_DECKS)


class TaroForm(StatesGroup):
    waiting_question = State()
    waiting_love_question = State()
    waiting_action_question = State()
    waiting_work_question = State()


def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🌅 Важное для меня сегодня"), KeyboardButton(text="✨ Голос внутреннего «Я»")],
            [KeyboardButton(text="💑 Расклад «Он и Она»"), KeyboardButton(text="🧭 Как поступить / не поступать")],
            [KeyboardButton(text="💼 Работа и карьера"), KeyboardButton(text="⚔️ Бизнес-расклад")],
            [KeyboardButton(text="❓ Задать свой вопрос картам"), KeyboardButton(text="💳 Баланс и пополнение")],
            [KeyboardButton(text="🕸 Витрина ловцов снов"), KeyboardButton(text="✨ О мастерской")],
        ],
        resize_keyboard=True,
    )
def buy_taro_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔮 1 глубокий расклад — 100 ⭐", callback_data="tbuy_1")],
            [InlineKeyboardButton(text="✨ Пакет 3 расклада — 250 ⭐", callback_data="tbuy_3")],
            [InlineKeyboardButton(text="🌟 Пакет 10 раскладов — 700 ⭐", callback_data="tbuy_10")],
            [
                InlineKeyboardButton(
                    text="🟣 Купить ⭐ (Kupikod)",
                    url="https://kupikod.com" + "/console/telegram",
                ),
                InlineKeyboardButton(
                    text="🔴 Купить ⭐ (МТС Оплата)",
                    url="https://" + "payment." + "mts.ru/tools/telegram-stars",
                ),
            ],
        ]
    )


def dreamcatchers_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📸 Смотреть каталог в Telegram-канале", url=DREAMCATCHERS_CHANNEL_URL)],
            [InlineKeyboardButton(text="🌿 Малый (до 15 см) — в авто / над столом", callback_data="dc_small")],
            [InlineKeyboardButton(text="🌙 Средний (15–20 см) — классика в спальню", callback_data="dc_medium")],
            [InlineKeyboardButton(text="🔥 Большой (20–25 см) — интерьерный оберег", callback_data="dc_large")],
            [InlineKeyboardButton(text="✨ Индивидуальный заказ под ваш запрос", callback_data="dc_custom")],
        ]
    )


def can_use_daily_free(user_id: int) -> bool:
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT last_free_date FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    last_date = next(iter(row), None) if row else None
    return last_date != today


def mark_daily_free_used(user_id: int):
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("UPDATE users SET last_free_date = ? WHERE user_id = ?", (today, user_id))
    conn.commit()


def get_paid_readings(user_id: int) -> int:
    cursor.execute("SELECT paid_readings FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    val = next(iter(row), 0) if row else 0
    return val if val is not None else 0


def spend_reading(user_id: int):
    if user_id in ADMIN_IDS:
        return
    cursor.execute("UPDATE users SET paid_readings = MAX(0, paid_readings - 1) WHERE user_id = ?", (user_id,))
    conn.commit()


MAJOR_ARCANA = [
    "Шут", "Маг", "Верховная Жрица", "Императрица", "Император", "Иерофант",
    "Влюблённые", "Колесница", "Сила", "Отшельник", "Колесо Фортуны", "Справедливость",
    "Повешенный", "Смерть", "Умеренность", "Дьявол", "Башня", "Звезда",
    "Луна", "Солнце", "Страшный Суд", "Мир",
]
SUITS = ["Жезлов", "Кубков", "Мечей", "Пентаклей"]
RANKS = ["Туз", "Двойка", "Тройка", "Четвёрка", "Пятёрка", "Шестёрка", "Семёрка", "Восьмёрка", "Девятка", "Десятка", "Паж", "Рыцарь", "Королева", "Король"]
TAROT_DECK = MAJOR_ARCANA + [f"{rank} {suit}" for suit in SUITS for rank in RANKS]


def draw_cards(count: int) -> str:
    picked = random.sample(TAROT_DECK, count)
    return ", ".join(f"{c} ({random.choice(['прямое положение', 'перевёрнутое положение'])})" for c in picked)


async def generate_taro_reading(spread_type: str, question: str, card_count: int = 3) -> str:
    deck = get_random_deck()
    drawn_cards = draw_cards(card_count)
    system_prompt = (
        f"Ты — глубокий, бережный и мудрый таролог. Для этого расклада ты берёшь в руки колоду: {deck}. "
        "ВАЖНО: обращайся к человеку строго гендерно-нейтрально, не используй слова в женском или мужском роде. "
        "Карты уже вытянуты из перемешанной колоды из 78 карт. Строго используй ТОЛЬКО те карты и их положения, которые указаны в запросе. "
        "Дай тёплую, понятную и точную трактовку. Пиши живым русским языком, структурируй абзацами с эмодзи, без звёздочек (**) и без решёток (#). "
        "Уложись в 1800 символов, чтобы текст легко читался одним сообщением."
    )
    user_msg = f"Тип расклада: {spread_type}.\nВыпавшие карты: {drawn_cards}.\nЗапрос человека: {question}"
    resp = await ai_client.chat.completions.create(
        model="deepseek/deepseek-v4.1-flash-1017-alt-lowcost",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.85,
    )
    first_choice = next(iter(resp.choices))
    return re.sub(r"^#+\s*", "", first_choice.message.content, flags=re.MULTILINE)
def stars_help_text(balance_label: str) -> str:
    return (
        f"💳 Твой баланс глубоких раскладов: {balance_label}.\n"
        f"🌅 «Важное для меня сегодня» доступно бесплатно 1 раз в день.\n\n"
        f"Оплата глубоких раскладов работает через официальную валюту Telegram — Stars (⭐).\n\n"
        f"🐣 Как пополнить звёзды за 30 секунд (если на счёте 0 ⭐):\n"
        f"1️⃣ Скопируй свой никнейм в Telegram (без знака @).\n"
        f"2️⃣ Нажми кнопку пополнения ниже (Kupikod или МТС Оплата), вставь свой ник и оплати пакет от 50 ⭐ картой РФ или через СБП (либо пополни любым привычным для тебя способом).\n"
        f"3️⃣ Звёзды придут на твой аккаунт в течение минуты — после этого просто выбери нужный пакет ниже 👇\n\n"
        f"⚠️ Важно: мы не являемся владельцами сторонних платёжных площадок (включая Kupikod, МТС Оплата и др.) и не несём ответственности за их работу, комиссии и зачисление средств с их стороны."
    )


@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, last_free_date, paid_readings) VALUES (?, ?, '', 1)",
        (message.from_user.id, message.from_user.username),
    )
    conn.commit()
    readings = get_paid_readings(message.from_user.id)
    await message.answer(
        "✨ Добро пожаловать в Мастерскую Таро и Ловцов Снов!\n\n"
        "• «🌅 Важное для меня сегодня» — бесплатная карта-фокус 1 раз в день;\n"
        f"• Глубокие расклады («Голос внутреннего «Я»», «Он и Она», «Как поступить», «Работа», «Бизнес», свой вопрос) — доступно: {readings} шт.\n"
        "• Ловцы снов ручной работы, сплетённые на живых лесных ветках.\n\n"
        "Выбирай действие в меню ниже 👇\n\n"
        "ℹ️ Расклады носят развлекательный и рекомендательный характер и не заменяют консультацию врача, юриста или финансового специалиста.",
        reply_markup=main_keyboard(),
    )


@dp.message(F.text == "💳 Баланс и пополнение")
async def show_balance(message: types.Message):
    bal = "Безлимит (Админ)" if message.from_user.id in ADMIN_IDS else f"{get_paid_readings(message.from_user.id)} шт."
    await message.answer(stars_help_text(bal), reply_markup=buy_taro_keyboard())


@dp.callback_query(F.data.startswith("tbuy_"))
async def process_taro_buy(callback: types.CallbackQuery):
    await callback.answer()
    pack = callback.data.replace("tbuy_", "")
    tariffs = {
        "1": ("1 глубокий расклад Таро", "Любой расклад: «Голос внутреннего «Я»», «Он и Она», «Как поступить», «Работа» или «Бизнес»", 100, "taro_pack_1"),
        "3": ("Пакет «3 расклада Таро»", "3 глубоких расклада на любую тему с трактовкой", 250, "taro_pack_3"),
        "10": ("Пакет «10 раскладов Таро»", "10 глубоких раскладов на любую тему с трактовкой", 700, "taro_pack_10"),
    }
    if pack not in tariffs:
        return
    title, desc, stars_amount, payload = tariffs[pack]
    await callback.message.answer_invoice(
        title=title, description=desc,
        prices=[LabeledPrice(label=title, amount=stars_amount)],
        provider_token="", payload=payload, currency="XTR",
    )


@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_q: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_q.id, ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    add_map = {"taro_pack_1": 1, "taro_pack_3": 3, "taro_pack_10": 10}
    added = add_map.get(message.successful_payment.invoice_payload, 0)
    cursor.execute("UPDATE users SET paid_readings = COALESCE(paid_readings, 0) + ? WHERE user_id = ?", (added, message.from_user.id))
    conn.commit()
    await message.answer(
        f"✨ Оплата прошла успешно! Начислено раскладов: +{added}.\nТекущий баланс: {get_paid_readings(message.from_user.id)} шт.",
        reply_markup=main_keyboard(),
    )
@dp.message(F.text == "🌅 Важное для меня сегодня")
async def today_important_card(message: types.Message):
    if not can_use_daily_free(message.from_user.id):
        await message.answer(
            "🌙 Твоё послание «Важное для меня сегодня» на сегодня уже открыто (эта кнопка срабатывает 1 раз в сутки).\n\n"
            "Возвращайся завтра за новой картой дня, а прямо сейчас можешь открыть глубокий расклад «✨ Голос внутреннего «Я»» или разобрать конкретную ситуацию 👇",
            reply_markup=buy_taro_keyboard(),
        )
        return
    wait_msg = await message.answer("🌅 Настраиваюсь на энергию твоего дня и вытягиваю главную карту...")
    try:
        reading = await generate_taro_reading(
            "Карта-фокус дня «Важное для меня сегодня» (1 карта: главный сигнал и энергия сегодняшнего дня, на чём держать фокус и от чего себя поберечь сегодня)",
            "Что самое важное мне нужно увидеть, почувствовать и учесть именно сегодня?",
            card_count=1,
        )
        mark_daily_free_used(message.from_user.id)
        await wait_msg.edit_text(reading)
    except Exception as e:
        await wait_msg.edit_text(f"Не удалось связаться с потоком: {e}")


@dp.message(F.text == "✨ Голос внутреннего «Я»")
async def inner_voice_spread(message: types.Message):
    if message.from_user.id not in ADMIN_IDS and get_paid_readings(message.from_user.id) <= 0:
        await message.answer("🌙 На балансе 0 глубоких раскладов. Выбери пакет ниже 👇", reply_markup=buy_taro_keyboard())
        return
    wait_msg = await message.answer("🕯 Прислушиваюсь к голосу твоего внутреннего «Я» на 3 картах: Внутреннее состояние — Скрытый ресурс — Бережный шаг для себя...")
    try:
        reading = await generate_taro_reading(
            "Глубокий расклад самопомощи «Голос внутреннего «Я»» (3 позиции: 1. Что сейчас на самом деле происходит внутри и забирает энергию; 2. Где спрятан твой внутренний ресурс, сила и опора; 3. Бережный практический шаг самопомощи, чтобы поддержать и восстановить себя)",
            "Помоги мне услышать голос моего внутреннего «Я»: что сейчас требует внимания, где моя опора и как мне бережно поддержать себя?",
            card_count=3,
        )
        spend_reading(message.from_user.id)
        await wait_msg.edit_text(reading)
    except Exception as e:
        await wait_msg.edit_text(f"Не удалось связаться с потоком: {e}")


@dp.message(F.text == "💑 Расклад «Он и Она»")
async def ask_love_spread(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS and get_paid_readings(message.from_user.id) <= 0:
        await message.answer("🌙 На балансе 0 глубоких раскладов. Выбери пакет ниже 👇", reply_markup=buy_taro_keyboard())
        return
    await message.answer("💑 Опиши кратко ситуацию в паре или имена/вопрос об отношениях одним сообщением (можно просто написать «Общий разбор нашей пары»):")
    await state.set_state(TaroForm.waiting_love_question)


@dp.message(TaroForm.waiting_love_question)
async def process_love_spread(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id not in ADMIN_IDS and get_paid_readings(message.from_user.id) <= 0:
        await message.answer("🌙 На балансе 0 глубоких раскладов. Выбери пакет ниже 👇", reply_markup=buy_taro_keyboard())
        return
    wait_msg = await message.answer("🕯 Выкладываю 4 карты «Он и Она»: Мысли и чувства Он — Мысли и чувства Она — Что между вами — Перспектива и совет...")
    try:
        reading = await generate_taro_reading(
            "Расклад на отношения «Он и Она» (4 позиции: 1. Его мысли, чувства и намерения; 2. Её мысли, чувства и намерения; 3. Энергия и суть происходящего между ними сейчас; 4. Перспектива развития и мудрый совет)",
            message.text,
            card_count=4,
        )
        spend_reading(message.from_user.id)
        await wait_msg.edit_text(reading)
    except Exception as e:
        await wait_msg.edit_text(f"Не удалось связаться с потоком: {e}")
@dp.message(F.text == "🧭 Как поступить / не поступать")
async def ask_action_spread(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS and get_paid_readings(message.from_user.id) <= 0:
        await message.answer("🌙 На балансе 0 глубоких раскладов. Выбери пакет ниже 👇", reply_markup=buy_taro_keyboard())
        return
    await message.answer("🧭 Опиши кратко ситуацию или выбор, перед которым ты сейчас стоишь — карты подскажут, как действовать, а чего лучше избежать:")
    await state.set_state(TaroForm.waiting_action_question)


@dp.message(TaroForm.waiting_action_question)
async def process_action_spread(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id not in ADMIN_IDS and get_paid_readings(message.from_user.id) <= 0:
        await message.answer("🌙 На балансе 0 глубоких раскладов. Выбери пакет ниже 👇", reply_markup=buy_taro_keyboard())
        return
    wait_msg = await message.answer("🕯 Выкладываю 3 карты: Ситуация — Как поступить — Чего точно не делать...")
    try:
        reading = await generate_taro_reading(
            "Расклад-навигатор «Как поступить / не поступать» (3 позиции: 1. Истинная суть ситуации сейчас; 2. Как стоит поступить — верный шаг; 3. Чего точно делать не стоит — главная ошибка)",
            message.text,
            card_count=3,
        )
        spend_reading(message.from_user.id)
        await wait_msg.edit_text(reading)
    except Exception as e:
        await wait_msg.edit_text(f"Не удалось связаться с потоком: {e}")


@dp.message(F.text == "💼 Работа и карьера")
async def ask_work_spread(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS and get_paid_readings(message.from_user.id) <= 0:
        await message.answer("🌙 На балансе 0 глубоких раскладов. Выбери пакет ниже 👇", reply_markup=buy_taro_keyboard())
        return
    await message.answer("💼 Напиши кратко свой вопрос или ситуацию по работе (например: перспективы роста, отношения с руководством и коллегами, стабильность позиции или смена работы):")
    await state.set_state(TaroForm.waiting_work_question)


@dp.message(TaroForm.waiting_work_question)
async def process_work_spread(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id not in ADMIN_IDS and get_paid_readings(message.from_user.id) <= 0:
        await message.answer("🌙 На балансе 0 глубоких раскладов. Выбери пакет ниже 👇", reply_markup=buy_taro_keyboard())
        return
    wait_msg = await message.answer("🕯 Выкладываю 4 карты по работе: Текущая позиция — Руководство и коллеги — Перспективы и риски — Верный шаг...")
    try:
        reading = await generate_taro_reading(
            "Расклад «Работа и карьера» (4 позиции: 1. Текущая позиция, устойчивость и реальный риск увольнения/сокращения; 2. Атмосфера в коллективе и отношение руководства; 3. Перспективы профессионального и финансового роста; 4. Главный практический шаг для укрепления позиций)",
            message.text,
            card_count=4,
        )
        spend_reading(message.from_user.id)
        await wait_msg.edit_text(reading)
    except Exception as e:
        await wait_msg.edit_text(f"Не удалось связаться с потоком: {e}")


@dp.message(F.text == "❓ Задать свой вопрос картам")
async def ask_taro(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS and get_paid_readings(message.from_user.id) <= 0:
        await message.answer("🌙 На балансе 0 глубоких раскладов. Выбери пакет ниже 👇", reply_markup=buy_taro_keyboard())
        return
    await message.answer("✨ Сформулируй свой вопрос или опиши ситуацию одним сообщением, и я вытяну 3 карты:")
    await state.set_state(TaroForm.waiting_question)


@dp.message(TaroForm.waiting_question)
async def process_taro_question(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id not in ADMIN_IDS and get_paid_readings(message.from_user.id) <= 0:
        await message.answer("🌙 На балансе 0 глубоких раскладов. Выбери пакет ниже 👇", reply_markup=buy_taro_keyboard())
        return
    wait_msg = await message.answer("🕯 Настраиваюсь на твой вопрос и открываю расклад...")
    try:
        reading = await generate_taro_reading("Расклад на 3 карты по личному вопросу", message.text, card_count=3)
        spend_reading(message.from_user.id)
        await wait_msg.edit_text(reading)
    except Exception as e:
        await wait_msg.edit_text(f"Не удалось связаться с потоком: {e}")


@dp.message(F.text == "⚔️ Бизнес-расклад")
async def kshatriya_business_spread(message: types.Message):
    if message.from_user.id not in ADMIN_IDS and get_paid_readings(message.from_user.id) <= 0:
        await message.answer("🌙 На балансе 0 глубоких раскладов. Выбери пакет ниже 👇", reply_markup=buy_taro_keyboard())
        return
    wait_msg = await message.answer("⚔️ Выкладываю 4 карты для диагностики дела: Лидер — Поле — Ресурс — Стратегический ход...")
    try:
        reading = await generate_taro_reading(
            "Бизнес-расклад (4 позиции: 1. Лидер и управленческая сила; 2. Внешнее поле и конкуренты; 3. Ресурсы, команда и инструменты; 4. Главный стратегический ход для роста)",
            "Проведи диагностику моего дела и стратегии роста: где моя сила, где уязвимость и какой шаг даст лучший результат.",
            card_count=4,
        )
        spend_reading(message.from_user.id)
        await wait_msg.edit_text(reading)
    except Exception as e:
        await wait_msg.edit_text(f"Не удалось связаться с потоком: {e}")


@dp.message(F.text == "🕸 Витрина ловцов снов")
async def show_dreamcatchers(message: types.Message):
    await message.answer(
        "🕸 ЛОВЦЫ СНОВ РУЧНОЙ РАБОТЫ\n\n"
        "Каждый ловец плетётся вручную с нуля на натуральных лесных ветках, с подбором перьев, камней и нитей под задачу хозяина.\n\n"
        "Посмотреть фото готовых работ, цены и задать вопросы в комментариях можно в нашем Telegram-канале, либо выбери формат ниже 👇",
        reply_markup=dreamcatchers_keyboard(),
    )


@dp.callback_query(F.data.startswith("dc_"))
async def dreamcatcher_details(callback: types.CallbackQuery):
    await callback.answer()
    items = {
        "dc_small": "🌿 МАЛЫЙ ЛОВЕЦ СНОВ (до 15 см)\n\n• Идеально для автомобиля, рабочего стола или над детской кроваткой.\n• Основа: натуральная гнутая ветка, хлопковая нить, натуральные перья и бусины.\n• Срок изготовления: 2–3 дня.\n\nДля заказа и выбора цветов напиши мастеру: @kata_nakata",
        "dc_medium": "🌙 СРЕДНИЙ ЛОВЕЦ СНОВ (15–20 см)\n\n• Классический размер для спальни: мягко фильтрует сны и украшает стену у изголовья.\n• Натуральная ветка, авторское плетение паутинки, подбор камней под ваш знак или запрос.\n• Срок изготовления: 3–4 дня.\n\nДля бронирования или подбора палитры напиши мастеру: @kata_nakata",
        "dc_large": "🔥 БОЛЬШОЙ ИНТЕРЬЕРНЫЙ ЛОВЕЦ (20–25 см)\n\n• Выразительный центральный оберег для комнаты или подарок со смыслом.\n• Сложная многоуровневая паутина, натуральные ветки, богатый каскад перьев и камней.\n• Срок изготовления: 4–5 дней.\n\nОбсудить детали и свободные изделия: @kata_nakata",
        "dc_custom": "✨ ИНДИВИДУАЛЬНЫЙ ЗАКАЗ ПОД ВАШ ЗАПРОС\n\n• Плетётся лично под человека, событие или конкретное намерение (спокойный сон, защита дома, подарок близкому).\n• Вместе с мастером подбираете размер, форму ветки, цветовую гамму и камни.\n\nНаписать мастеру для обсуждения идеи: @kata_nakata",
    }
    await callback.message.answer(items.get(callback.data, "Напиши мастеру: @kata_nakata"))


@dp.message(F.text == "✨ О мастерской")
async def about_workshop(message: types.Message):
    await message.answer(
        "✨ О МАСТЕРСКОЙ\n\n"
        "• Таро: авторские расклады с опорой на многолетнюю практику и живые тетради трактовок.\n"
        "• Ловцы снов: 100% ручная работа — от поиска и сушки лесных веток до последнего пёрышка.\n"
        "• Время работы мастерской: ежедневно с 12:00 до 18:00.\n\n"
        "По любым вопросам и заказам: @kata_nakata"
    )


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
