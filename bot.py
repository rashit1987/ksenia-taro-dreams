import asyncio
import logging
import os
import random
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
VSEGPT_API_KEY = os.getenv("VSEGPT_API_KEY", "").strip()

ADMIN_IDS = {1795533772, 1273001338}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
ai_client = AsyncOpenAI(api_key=VSEGPT_API_KEY, base_url="https://" + "api.vsegpt.ru/v1", timeout=60.0)

conn = sqlite3.connect("taro_ksenia.db")
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, last_free_date TEXT)")
conn.commit()

DAILY_DECKS = [
    "Классическая колода Райдера-Уэйта (тёплый символизм и архетипы)",
    "Мистическое Таро Ночного Леса (глубокая интуиция и природные образы)",
    "Неоновое Кибер-Таро будущего (острые, современные и прямые трактовки)",
    "Таро Светлого Провидца (мягкая психология и поддержка)",
    "Готическое Таро Теней (честный разбор скрытых мотивов)",
    "Таро Золотого Арт-Нуво (эстетика, чувства и гармония)",
    "Таро Древних Славянских Снов (мудрость предков и знаки судьбы)",
]

def get_today_deck() -> str:
    day_idx = datetime.now().weekday()
    return DAILY_DECKS[day_idx]

class TaroForm(StatesGroup):
    waiting_question = State()

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔮 Карта дня"), KeyboardButton(text="🃏 Расклад на 3 карты")],
            [KeyboardButton(text="❓ Свой вопрос картам"), KeyboardButton(text="⚔️ Бизнес-расклад (Кшатрии)")],
            [KeyboardButton(text="🕸 Витрина ловцов снов"), KeyboardButton(text="✨ О мастерской")],
        ],
        resize_keyboard=True,
    )

def dreamcatchers_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌿 Малый (до 15 см) — в авто / над столом", callback_data="dc_small")],
            [InlineKeyboardButton(text="🌙 Средний (15–20 см) — классика в спальню", callback_data="dc_medium")],
            [InlineKeyboardButton(text="🔥 Большой (20–25 см) — интерьерный оберег", callback_data="dc_large")],
            [InlineKeyboardButton(text="✨ Индивидуальный заказ под ваш запрос", callback_data="dc_custom")],
        ]
    )

def can_use_free(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT last_free_date FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    last_date = next(iter(row), None) if row else None
    return last_date != today

def mark_free_used(user_id: int):
    if user_id in ADMIN_IDS:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("UPDATE users SET last_free_date = ? WHERE user_id = ?", (today, user_id))
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
    result = []
    for card in picked:
        pos = random.choice(["прямое положение", "перевёрнутое положение"])
        result.append(f"{card} ({pos})")
    return ", ".join(result)

async def generate_taro_reading(spread_type: str, question: str) -> str:
    deck = get_today_deck()
    count = 1 if "1 карта" in spread_type else 3
    drawn_cards = draw_cards(count)
        system_prompt = (
        f"Ты — глубокий, бережный и мудрый таролог. Сегодня ты работаешь на колоде: {deck}. "
        "ВАЖНО: обращайся к человеку строго гендерно-нейтрально, не используй слова в женском или мужском роде (никаких 'самой', 'дорогая', 'выносила', 'решил'). Используй нейтральные обороты ('тебе', 'в твоём случае', 'стоит обратить внимание'). "
        "Карты уже вытянуты из перемешанной колоды из 78 карт. Строго используй ТОЛЬКО те карты и их положения, которые указаны в запросе, не меняй их на другие. "
        "Дай тёплую, понятную и точную трактовку. Пиши живым русским языком с лёгкой мистической атмосферой, структурируй абзацами с эмодзи, без символов звёздочек (**). "
        "Уложись в 1800 символов, чтобы текст легко читался одним сообщением."
    )
    user_msg = f"Тип расклада: {spread_type}.\nВыпавшие карты: {drawn_cards}.\nЗапрос человека: {question}"
    resp = await ai_client.chat.completions.create(
        model="deepseek/deepseek-v4.1-flash-1017-alt-lowcost",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.8,
    )
    first_choice = next(iter(resp.choices))
    return first_choice.message.content

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, last_free_date) VALUES (?, ?, '')",
        (message.from_user.id, message.from_user.username),
    )
    conn.commit()
    deck = get_today_deck()
    await message.answer(
        "✨ Добро пожаловать в Мастерскую Таро и Ловцов Снов!\n\n"
        f"🃏 Колода дня сегодня:\n{deck}\n\n"
        "Здесь можно вытянуть карту дня, сделать расклад на любую ситуацию или выбрать ловец снов ручной работы, сплетённый на живых ветках.\n\n"
        "Выбирай действие в меню ниже 👇",
        reply_markup=main_keyboard(),
    )

@dp.message(F.text == "🔮 Карта дня")
async def card_of_day(message: types.Message):
    if not can_use_free(message.from_user.id):
        await message.answer("🌙 Бесплатный расклад на сегодня уже использован. Возвращайся завтра за новой картой дня или загляни в витрину ловцов снов!")
        return
    wait_msg = await message.answer("🕯 Перетасовываю колоду дня и тяну карту...")
    try:
        reading = await generate_taro_reading("Карта дня (1 карта)", "Какая главная энергия и совет ждут меня сегодня?")
        mark_free_used(message.from_user.id)
        await wait_msg.edit_text(reading)
    except Exception as e:
        await wait_msg.edit_text(f"Не удалось связаться с потоком: {e}")

@dp.message(F.text == "🃏 Расклад на 3 карты")
async def three_cards(message: types.Message):
    if not can_use_free(message.from_user.id):
        await message.answer("🌙 Бесплатный расклад на сегодня уже использован. Новая попытка откроется завтра!")
        return
    wait_msg = await message.answer("🕯 Выкладываю три карты: Прошлое — Настоящее — Будущее...")
    try:
        reading = await generate_taro_reading("Расклад на 3 карты (Прошлое / Настоящее / Будущее)", "Общий вектор развития моей текущей ситуации и куда лучше направить силы.")
        mark_free_used(message.from_user.id)
        await wait_msg.edit_text(reading)
    except Exception as e:
        await wait_msg.edit_text(f"Не удалось связаться с потоком: {e}")

@dp.message(F.text == "❓ Задать свой вопрос картам")
async def ask_taro(message: types.Message, state: FSMContext):
    if not can_use_free(message.from_user.id):
        await message.answer("🌙 Бесплатный расклад на сегодня уже использован. Жду тебя завтра!")
        return
    await message.answer("✨ Сформулируй свой вопрос или опиши ситуацию одним сообщением, и я вытяну 3 карты:")
    await state.set_state(TaroForm.waiting_question)

@dp.message(TaroForm.waiting_question)
async def process_taro_question(message: types.Message, state: FSMContext):
    await state.clear()
    wait_msg = await message.answer("🕯 Настраиваюсь на твой вопрос и открываю расклад...")
    try:
        reading = await generate_taro_reading("Расклад на 3 карты по личному вопросу", message.text)
        mark_free_used(message.from_user.id)
        await wait_msg.edit_text(reading)
    except Exception as e:
        await wait_msg.edit_text(f"Не удалось связаться с потоком: {e}")

@dp.message(F.text == "⚔️ Бизнес-расклад (Кшатрии)")
async def kshatriya_business_spread(message: types.Message):
    if not can_use_free(message.from_user.id):
        await message.answer("🌙 Бесплатный расклад на сегодня уже использован. Новая попытка откроется завтра!")
        return
    wait_msg = await message.answer("⚔️ Выкладываю 4 карты по системе Кшатриев: Лидер — Поле боя — Ресурс — Стратегический ход...")
    try:
        reading = await generate_taro_reading(
            "Бизнес-расклад по системе Кшатриев (4 позиции: 1. Лидер и управленческая сила; 2. Внешнее поле и конкуренты; 3. Ресурсы, команда и инструменты; 4. Главный стратегический ход для победы)",
            "Проведи диагностику моего дела и стратегии роста по касте Кшатриев: где моя сила, где уязвимость и как действовать как лидер.",
        )
        mark_free_used(message.from_user.id)
        await wait_msg.edit_text(reading)
    except Exception as e:
        await wait_msg.edit_text(f"Не удалось связаться с потоком: {e}")

@dp.message(F.text == "🕸 Витрина ловцов снов")
async def show_dreamcatchers(message: types.Message):
    await message.answer(
        "🕸 ЛОВЦЫ СНОВ РУЧНОЙ РАБОТЫ\n\n"
        "Каждый ловец плетётся вручную с нуля на натуральных лесных ветках, с подбором перьев, камней и нитей под задачу хозяина.\n\n"
        "Выбери подходящий формат, чтобы узнать детали:",
        reply_markup=dreamcatchers_keyboard(),
    )

@dp.callback_query(F.data.startswith("dc_"))
async def dreamcatcher_details(callback: types.CallbackQuery):
    await callback.answer()
    items = {
        "dc_small": (
            "🌿 МАЛЫЙ ЛОВЕЦ СНОВ (до 15 см)\n\n"
            "• Идеально для автомобиля, рабочего стола или над детской кроваткой.\n"
            "• Основа: натуральная гнутая ветка, хлопковая нить, натуральные перья и бусины.\n"
            "• Срок изготовления: 2–3 дня.\n\n"
            "Для заказа и выбора цветов напиши мастеру: @kata_nakata"
        ),
        "dc_medium": (
            "🌙 СРЕДНИЙ ЛОВЕЦ СНОВ (15–20 см)\n\n"
            "• Классический размер для спальни: мягко фильтрует сны и украшает стену у изголовья.\n"
            "• Натуральная ветка, авторское плетение паутинки, подбор камней под ваш знак или запрос.\n"
            "• Срок изготовления: 3–4 дня.\n\n"
            "Для бронирования или подбора палитры напиши мастеру: @kata_nakata"
        ),
        "dc_large": (
            "🔥 БОЛЬШОЙ ИНТЕРЬЕРНЫЙ ЛОВЕЦ (20–25 см)\n\n"
            "• Выразительный центральный оберег для комнаты или подарок со смыслом.\n"
            "• Сложная многоуровневая паутина, натуральные ветки, богатый каскад перьев и камней.\n"
            "• Срок изготовления: 4–5 дней.\n\n"
            "Обсудить детали и свободные изделия: @kata_nakata"
        ),
        "dc_custom": (
            "✨ ИНДИВИДУАЛЬНЫЙ ЗАКАЗ ПОД ВАШ ЗАПРОС\n\n"
            "• Плетётся лично под человека, событие или конкретное намерение (спокойный сон, защита дома, подарок близкому).\n"
            "• Вместе с мастером подбираете размер, форму ветки, цветовую гамму и камни.\n\n"
            "Написать мастеру для обсуждения идеи: @kata_nakata"
        ),
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
