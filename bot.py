import asyncio
import os
import re
import html
from datetime import datetime
from difflib import SequenceMatcher

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, FSInputFile
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from database import (
    init_db,
    add_transaction,
    get_balance,
    get_transactions,
    archive_all,
    get_archived_transactions,
)


# =========================================================
# SOZLAMALAR
# =========================================================

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN .env faylida topilmadi"
    )

# Barcha ma'lumotlarni arxivlash uchun admin parol
ADMIN_PASSWORD = "admin123"

bot = Bot(token=TOKEN)
dp = Dispatcher()


# =========================================================
# STATES
# =========================================================

class ExpenseState(StatesGroup):
    product = State()
    quantity = State()
    unit = State()
    price = State()


class IncomeState(StatesGroup):
    amount = State()


class AdminClearState(StatesGroup):
    password = State()


# =========================================================
# ASOSIY MENYU
# =========================================================

def main_keyboard():
    builder = ReplyKeyboardBuilder()

    buttons = [
        "➕ Xarajat qo‘shish",
        "💵 Daromad qo‘shish",

        "📊 Hisobot",
        "💰 Balans",

        "💳 Pul tarixi",
        "📦 Yuk tarixi",

        "🗄 Arxiv",
        "📥 Excel",

        "🗑 Tozalash",
    ]

    for button in buttons:
        builder.button(text=button)

    builder.adjust(
        2,
        2,
        2,
        2,
        1
    )

    return builder.as_markup(
        resize_keyboard=True
    )


# =========================================================
# ORQAGA TUGMASI
# =========================================================

def back_keyboard():
    builder = ReplyKeyboardBuilder()

    builder.button(
        text="⬅️ Orqaga"
    )

    return builder.as_markup(
        resize_keyboard=True
    )


@dp.message(F.text == "⬅️ Orqaga")
async def go_back(
    message: Message,
    state: FSMContext
):
    await state.clear()

    await message.answer(
        "↩️ <b>Asosiy menyuga qaytdingiz.</b>\n\n"
        "Kerakli amalni tanlang:",
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )


# =========================================================
# YORDAMCHI FUNKSIYALAR
# =========================================================

def money(value):
    value = float(value)

    if value.is_integer():
        value = int(value)

    return (
        f"{value:,.0f}"
        .replace(",", " ")
        + " so‘m"
    )


def qty(value):
    value = float(value)
    return f"{value:g}"


def now():
    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def parse_money(text):

    text = text.lower().strip()

    for x in (
        "so'm",
        "so‘m",
        "sum",
        "сум"
    ):
        text = text.replace(x, "")

    # 1 mln
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*"
        r"(mln|million|млн)",
        text
    )

    if match:
        return (
            float(
                match.group(1)
                .replace(",", ".")
            )
            * 1_000_000
        )

    # 500 ming
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*"
        r"(ming|тыс)",
        text
    )

    if match:
        return (
            float(
                match.group(1)
                .replace(",", ".")
            )
            * 1_000
        )

    # 10k
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*k\b",
        text
    )

    if match:
        return (
            float(
                match.group(1)
                .replace(",", ".")
            )
            * 1_000
        )

    cleaned = re.sub(
        r"[^\d.,]",
        "",
        text
    )

    if not cleaned:
        return None

    try:

        if "," in cleaned and "." not in cleaned:
            cleaned = cleaned.replace(",", "")

        elif "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(",", "")

        return float(cleaned)

    except ValueError:
        return None


def similarity(a, b):
    return SequenceMatcher(
        None,
        a.lower(),
        b.lower()
    ).ratio()


def detect_command(text):

    text = text.lower().strip()

    commands = {

        "report": [
            "hisobot",
            "xisobot",
            "xizobot",
            "hisobat",
            "hisobotni ber",
            "hisobimni ber",
        ],

        "expense": [
            "xarajat",
            "xarajat qo‘sh",
            "xarajat qosh",
            "harajat",
            "harajat qo‘sh",
            "harajat qosh",
            "xarajat kirit",
            "chiqim",
            "chiqim qo‘sh",
        ],

        "income": [
            "daromad",
            "daromat",
            "kirim",
            "pul qo‘sh",
            "pul qosh",
            "daromad qo‘sh",
            "daromad qosh",
        ],

        "balance": [
            "balans",
            "qoldiq",
            "qancha pulim bor",
            "pulim qancha",
            "hisobim",
        ],

        "history": [
            "tarix",
            "operatsiyalar",
            "xarajatlarim",
            "kirimlarim",
        ],
    }

    best_command = None
    best_score = 0

    for command, variants in commands.items():

        for variant in variants:

            if variant in text:
                return command

            score = similarity(
                text,
                variant
            )

            if score > best_score:
                best_score = score
                best_command = command

    if best_score >= 0.58:
        return best_command

    return None


# =========================================================
# ODDIY CHATDAN XARAJAT ANIQLASH
# =========================================================

def parse_expense_text(text):

    """
    Misollar:

    3 kg olma oldim 18000

    5 kg kartoshka 8000

    2 litr yog 25000

    10 dona non 4000
    """

    text = text.lower()

    remove_words = [
        "bugun",
        "oldim",
        "sotib oldim",
        "xarajat",
        "xarajat qildim",
        "uchun",
        "menga",
        "yozib qo‘y",
        "yozib qoy",
    ]

    for word in remove_words:
        text = text.replace(
            word,
            " "
        )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    quantity_match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*"
        r"(kg|kilo|kilogram|litr|litre|l|dona|ta)\b",
        text
    )

    if not quantity_match:
        return None

    quantity = float(
        quantity_match
        .group(1)
        .replace(",", ".")
    )

    unit_raw = quantity_match.group(2)

    if unit_raw in (
        "kg",
        "kilo",
        "kilogram"
    ):
        unit = "kg"

    elif unit_raw in (
        "l",
        "litr",
        "litre"
    ):
        unit = "litr"

    else:
        unit = "dona"

    after_quantity = text[
        quantity_match.end():
    ]

    price = parse_money(
        after_quantity
    )

    if price is None:
        return None

    before_quantity = text[
        :quantity_match.start()
    ].strip()

    after_words = re.sub(
        r"^\s*[,.\-:]+\s*",
        "",
        after_quantity
    )

    product_name = before_quantity

    if not product_name:

        product_name = after_words

        product_name = re.sub(
            r"\d+(?:[.,]\d+)?\s*"
            r"(ming|mln|million|k)?",
            "",
            product_name
        )

    product_name = product_name.strip(
        " ,.-"
    )

    if not product_name:
        return None

    return {
        "product_name":
            product_name.title(),

        "quantity":
            quantity,

        "unit":
            unit,

        "unit_price":
            price,

        "total":
            quantity * price,
    }


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start(
    message: Message,
    state: FSMContext
):

    await state.clear()

    await message.answer(
        "👋 <b>Assalomu alaykum!</b>\n\n"
        "💰 Men sizning moliyaviy yordamchingizman.\n\n"

        "📦 Masalan:\n"
        "<i>3 kg olma oldim, kilosi 18000</i>\n\n"

        "Bot buni avtomatik ravishda "
        "<b>xarajat</b> deb hisoblaydi.\n\n"

        "54 000 so‘m balansdan ayriladi.\n\n"

        "👇 Menyudan foydalaning.",

        reply_markup=main_keyboard(),

        parse_mode="HTML",
    )


# =========================================================
# XARAJAT QO‘SHISH
# =========================================================

@dp.message(
    F.text == "➕ Xarajat qo‘shish"
)
async def expense_button(
    message: Message,
    state: FSMContext
):

    await state.set_state(
        ExpenseState.product
    )

    await message.answer(
        "📦 <b>Mahsulot nomini kiriting:</b>\n\n"
        "Masalan: <i>Olma</i>",

        reply_markup=back_keyboard(),

        parse_mode="HTML",
    )


# =========================================================
# MAHSULOT NOMI
# =========================================================

@dp.message(
    ExpenseState.product
)
async def expense_product(
    message: Message,
    state: FSMContext
):

    await state.update_data(
        product_name=
        message.text.strip()
    )

    await state.set_state(
        ExpenseState.quantity
    )

    await message.answer(
        "⚖️ <b>Miqdorini kiriting:</b>\n\n"
        "Masalan:\n"
        "• 3 kg\n"
        "• 2 litr\n"
        "• 10 dona",

        reply_markup=back_keyboard(),

        parse_mode="HTML",
    )


# =========================================================
# MIQDOR
# =========================================================

@dp.message(
    ExpenseState.quantity
)
async def expense_quantity(
    message: Message,
    state: FSMContext
):

    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*"
        r"(kg|kilo|litr|l|dona|ta)?",

        message.text.lower()
    )

    if not match:

        await message.answer(
            "❌ <b>Miqdorni tushunmadim.</b>\n\n"
            "Masalan: <b>3 kg</b>\n\n"
            "Yoki jarayonni bekor qilish uchun "
            "<b>⬅️ Orqaga</b> bosing.",

            reply_markup=back_keyboard(),

            parse_mode="HTML",
        )

        return

    quantity = float(
        match.group(1)
        .replace(",", ".")
    )

    unit_raw = match.group(2)

    if unit_raw in (
        "kg",
        "kilo"
    ):
        unit = "kg"

    elif unit_raw in (
        "litr",
        "l"
    ):
        unit = "litr"

    elif unit_raw in (
        "dona",
        "ta"
    ):
        unit = "dona"

    else:
        unit = None

    await state.update_data(
        quantity=quantity,
        unit=unit
    )

    await state.set_state(
        ExpenseState.unit
    )

    await message.answer(
        "📏 <b>Birlikni kiriting:</b>\n\n"
        "kg / litr / dona",

        reply_markup=back_keyboard(),

        parse_mode="HTML",
    )


# =========================================================
# BIRLIK
# =========================================================

@dp.message(
    ExpenseState.unit
)
async def expense_unit(
    message: Message,
    state: FSMContext
):

    unit = message.text.lower().strip()

    if (
        "kg" in unit
        or "kilo" in unit
    ):
        unit = "kg"

    elif (
        "litr" in unit
        or unit == "l"
    ):
        unit = "litr"

    elif (
        "dona" in unit
        or unit == "ta"
    ):
        unit = "dona"

    else:

        await message.answer(
            "❌ <b>Birlikni tushunmadim.</b>\n\n"
            "kg, litr yoki dona yozing.",

            reply_markup=back_keyboard(),

            parse_mode="HTML",
        )

        return

    await state.update_data(
        unit=unit
    )

    await state.set_state(
        ExpenseState.price
    )

    await message.answer(
        "💰 <b>1 birlik narxini kiriting:</b>\n\n"
        "Masalan: <b>18000</b>\n"
        "yoki <b>18 ming</b>",

        reply_markup=back_keyboard(),

        parse_mode="HTML",
    )


# =========================================================
# NARX
# =========================================================

@dp.message(
    ExpenseState.price
)
async def expense_price(
    message: Message,
    state: FSMContext
):

    price = parse_money(
        message.text
    )

    if price is None:

        await message.answer(
            "❌ <b>Narxni tushunmadim.</b>\n\n"
            "Masalan: <b>18000</b>",

            reply_markup=back_keyboard(),

            parse_mode="HTML",
        )

        return

    data = await state.get_data()

    quantity = data["quantity"]
    unit = data["unit"]
    product_name = data[
        "product_name"
    ]

    total = quantity * price

    # MUHIM:
    # Xarajat sifatida saqlanadi.
    # Shuning uchun balansdan ayriladi.
    await add_transaction(

        user_id=
            message.from_user.id,

        transaction_type=
            "expense",

        total=
            total,

        created_at=
            now(),

        product_name=
            product_name,

        quantity=
            quantity,

        unit=
            unit,

        unit_price=
            price,

        category=
            "Yuk xaridi",
    )

    await state.clear()

    income, expense = await get_balance(
        message.from_user.id
    )

    balance = income - expense

    await message.answer(

        "📦 <b>YUK OLINDI</b>\n\n"

        f"📌 <b>{html.escape(product_name)}</b>\n"

        f"⚖️ <b>{qty(quantity)} {unit}</b>\n"

        f"💰 {money(price)} / {unit}\n"

        f"🧮 <b>Jami: {money(total)}</b>\n\n"

        f"🔴 Puldan ayrildi: "
        f"<b>-{money(total)}</b>\n"

        f"💰 Qoldiq: "
        f"<b>{money(balance)}</b>\n\n"

        f"🕐 {now()}",

        reply_markup=
            main_keyboard(),

        parse_mode="HTML",
    )


# =========================================================
# DAROMAD
# =========================================================

@dp.message(
    F.text == "💵 Daromad qo‘shish"
)
async def income_button(
    message: Message,
    state: FSMContext
):

    await state.set_state(
        IncomeState.amount
    )

    await message.answer(

        "💵 <b>Qancha pul qo‘shildi?</b>\n\n"

        "Masalan:\n"
        "• 1000000\n"
        "• 1 mln\n"
        "• 500 ming",

        reply_markup=
            back_keyboard(),

        parse_mode="HTML",
    )


# =========================================================
# DAROMAD SUMMASI
# =========================================================

@dp.message(
    IncomeState.amount
)
async def income_amount(
    message: Message,
    state: FSMContext
):

    amount = parse_money(
        message.text
    )

    if amount is None:

        await message.answer(
            "❌ <b>Summani tushunmadim.</b>\n\n"
            "Masalan: <b>1000000</b>",

            reply_markup=
                back_keyboard(),

            parse_mode="HTML",
        )

        return

    await add_transaction(

        user_id=
            message.from_user.id,

        transaction_type=
            "income",

        total=
            amount,

        created_at=
            now(),

        category=
            "Daromad",
    )

    await state.clear()

    income, expense = await get_balance(
        message.from_user.id
    )

    balance = income - expense

    await message.answer(

        "🟢 <b>PUL KIRDI</b>\n\n"

        f"💰 <b>+{money(amount)}</b>\n"

        f"💰 Qoldiq: "
        f"<b>{money(balance)}</b>\n"

        f"🕐 {now()}",

        reply_markup=
            main_keyboard(),

        parse_mode="HTML",
    )


# =========================================================
# BALANS
# =========================================================

async def send_balance(
    message: Message
):

    income, expense = await get_balance(
        message.from_user.id
    )

    balance = income - expense

    await message.answer(

        "💰 <b>BALANS</b>\n\n"

        f"🟢 Kirim: "
        f"<b>{money(income)}</b>\n"

        f"🔴 Chiqim: "
        f"<b>{money(expense)}</b>\n"

        f"💰 Qoldiq: "
        f"<b>{money(balance)}</b>",

        parse_mode="HTML",
    )


# =========================================================
# HISOBOT
# =========================================================

async def send_report(
    message: Message
):

    income, expense = await get_balance(
        message.from_user.id
    )

    balance = income - expense

    await message.answer(

        "📊 <b>MOLIYAVIY HISOBOT</b>\n\n"

        f"🟢 Jami kirim: "
        f"<b>{money(income)}</b>\n\n"

        f"🔴 Jami xarajat: "
        f"<b>{money(expense)}</b>\n\n"

        f"💰 Qoldiq: "
        f"<b>{money(balance)}</b>",

        parse_mode="HTML",
    )


# =========================================================
# PUL TARIXI
# =========================================================

async def send_money_history(
    message: Message
):

    rows = await get_transactions(
        message.from_user.id
    )

    rows = [
        r for r in rows
        if r[1] in (
            "income",
            "expense"
        )
    ]

    if not rows:

        await message.answer(
            "📭 <b>Pul tarixi bo‘sh.</b>",
            parse_mode="HTML",
        )

        return

    text = (
        "💳 <b>PUL KIRISH / CHIQISH TARIXI</b>\n\n"
    )

    for item in rows[:50]:

        (
            _id,
            t_type,
            product,
            quantity,
            unit,
            unit_price,
            total,
            category,
            note,
            created_at,
            deleted_at,
        ) = item

        if t_type == "income":

            text += (

                "🟢 <b>PUL KIRDI</b>\n"

                f"💰 "
                f"<b>+{money(total)}</b>\n"

                f"🕐 {created_at}\n"

                "━━━━━━━━━━━━\n"
            )

        else:

            text += (

                "🔴 <b>PUL CHIQDI</b>\n"

                f"📦 "
                f"{html.escape(product or 'Yuk')}\n"

                f"⚖️ "
                f"{qty(quantity or 0)} "
                f"{unit or ''}\n"

                f"💰 "
                f"<b>-{money(total)}</b>\n"

                f"🕐 {created_at}\n"

                "━━━━━━━━━━━━\n"
            )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# =========================================================
# YUK TARIXI
# =========================================================

async def send_goods_history(
    message: Message
):

    rows = await get_transactions(
        message.from_user.id,
        transaction_type="expense",
    )

    if not rows:

        await message.answer(
            "📭 <b>Yuk tarixi bo‘sh.</b>",
            parse_mode="HTML",
        )

        return

    text = (
        "📦 <b>YUK OLINGAN TARIXI</b>\n\n"
    )

    for item in rows[:50]:

        (
            _id,
            _type,
            product,
            quantity,
            unit,
            unit_price,
            total,
            _category,
            _note,
            created_at,
            _deleted_at,
        ) = item

        text += (

            "📦 <b>YUK OLINDI</b>\n"

            f"📌 "
            f"{html.escape(product or 'Noma’lum')}\n"

            f"⚖️ <b>"
            f"{qty(quantity or 0)} "
            f"{unit or ''}"
            f"</b>\n"

            f"💰 "
            f"{money(unit_price or 0)}"
            f" / {unit or ''}\n"

            f"🧮 <b>Jami: "
            f"{money(total)}</b>\n"

            f"🕐 {created_at}\n"

            "━━━━━━━━━━━━\n"
        )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# =========================================================
# ARXIV
# =========================================================

async def send_archive(
    message: Message
):

    rows = await get_archived_transactions(
        message.from_user.id
    )

    rows = [
        r for r in rows
        if r[10] is not None
    ]

    if not rows:

        await message.answer(
            "🗄 <b>Arxiv bo‘sh.</b>",
            parse_mode="HTML",
        )

        return

    text = (
        "🗄 <b>ARXIV</b>\n\n"
    )

    for item in rows[:50]:

        (
            _id,
            t_type,
            product,
            quantity,
            unit,
            unit_price,
            total,
            _category,
            _note,
            created_at,
            deleted_at,
        ) = item

        if t_type == "income":

            text += (

                "🟢 <b>PUL KIRDI</b>\n"

                f"💰 {money(total)}\n"

                f"🕐 {created_at}\n"

                f"🗄 Arxiv: {deleted_at}\n"

                "━━━━━━━━━━━━\n"
            )

        else:

            text += (

                "📦 <b>YUK OLINDI</b>\n"

                f"📌 "
                f"{html.escape(product or 'Yuk')}\n"

                f"⚖️ "
                f"{qty(quantity or 0)} "
                f"{unit or ''}\n"

                f"💰 {money(total)}\n"

                f"🕐 {created_at}\n"

                f"🗄 Arxiv: {deleted_at}\n"

                "━━━━━━━━━━━━\n"
            )

    await message.answer(
        text,
        parse_mode="HTML"
    )


# =========================================================
# EXCEL
# =========================================================

async def export_excel(
    message: Message
):

    try:

        from openpyxl import Workbook

    except ImportError:

        await message.answer(

            "❌ Excel kutubxonasi topilmadi.\n\n"

            "Terminalda:\n"

            "<code>pip install openpyxl</code>",

            parse_mode="HTML",
        )

        return

    rows = await get_transactions(
        message.from_user.id,
        include_archived=True,
    )

    if not rows:

        await message.answer(
            "📭 Excelga chiqariladigan "
            "ma’lumot yo‘q."
        )

        return

    wb = Workbook()

    ws = wb.active

    ws.title = "Barcha tarix"

    headers = [

        "ID",
        "Turi",
        "Mahsulot",
        "Miqdor",
        "Birlik",
        "Birlik narxi",
        "Jami",
        "Kategoriya",
        "Izoh",
        "Sana",
        "Holat",
        "Arxivlangan vaqt",
    ]

    ws.append(headers)

    for item in rows:

        (
            transaction_id,
            t_type,
            product,
            quantity,
            unit,
            unit_price,
            total,
            category,
            note,
            created_at,
            deleted_at,
        ) = item

        ws.append([

            transaction_id,

            "PUL KIRDI"
            if t_type == "income"
            else "YUK/PUL CHIQDI",

            product or "",

            quantity or "",

            unit or "",

            unit_price or "",

            total,

            category or "",

            note or "",

            created_at,

            "ARXIV"
            if deleted_at
            else "FAOL",

            deleted_at or "",
        ])

    for cell in ws[1]:

        cell.font = cell.font.copy(
            bold=True
        )

    for column in ws.columns:

        max_len = max(
            len(
                str(
                    cell.value or ""
                )
            )
            for cell in column
        )

        ws.column_dimensions[
            column[0].column_letter
        ].width = min(
            max_len + 2,
            30
        )

    filename = (
        f"hisobot_"
        f"{message.from_user.id}_"
        f"{datetime.now():%Y%m%d_%H%M%S}"
        f".xlsx"
    )

    wb.save(filename)

    await message.answer_document(

        FSInputFile(filename),

        caption=(
            "📥 <b>Excel tayyor.</b>\n\n"
            "Faol va arxivdagi "
            "ma’lumotlar ham kiritildi."
        ),

        parse_mode="HTML",
    )

    try:
        os.remove(filename)
    except OSError:
        pass


# =========================================================
# BARCHA MA'LUMOTLARNI TOZALASH
# =========================================================

@dp.message(
    F.text == "🗑 Tozalash"
)
async def clear_request(
    message: Message,
    state: FSMContext
):

    await state.set_state(
        AdminClearState.password
    )

    await message.answer(

        "🔐 <b>ADMIN TASDIQLASH</b>\n\n"

        "Barcha ma’lumotlarni "
        "tozalab, arxivga saqlash uchun "
        "admin parolini kiriting.\n\n"

        "🔑 <b>Parol:</b>",

        reply_markup=
            back_keyboard(),

        parse_mode="HTML",
    )


# =========================================================
# ADMIN PAROL
# =========================================================

@dp.message(
    AdminClearState.password
)
async def admin_clear_password(
    message: Message,
    state: FSMContext
):

    password = message.text.strip()

    if password != ADMIN_PASSWORD:

        await state.clear()

        await message.answer(

            "❌ <b>Parol noto‘g‘ri!</b>\n\n"

            "Ma’lumotlar o‘chirilmagan.",

            reply_markup=
                main_keyboard(),

            parse_mode="HTML",
        )

        return

    # MUHIM:
    # Fizik o‘chirmaydi.
    # Hammasini arxivga ko‘chiradi.
    count = await archive_all(
        message.from_user.id
    )

    await state.clear()

    await message.answer(

        "🗑 <b>BARCHA MA’LUMOTLAR TOZALANDI</b>\n\n"

        f"📊 Arxivga ko‘chirilgan: "
        f"<b>{count} ta</b>\n\n"

        "🗄 Barcha ma’lumotlar "
        "<b>ARXIVDA SAQLANDI</b>.\n\n"

        "❗ Ma’lumotlar butunlay "
        "o‘chirilmagan.\n\n"

        "📂 <b>Arxiv</b> orqali ko‘rish mumkin.\n"
        "📥 <b>Excel</b> orqali yuklab olish mumkin.",

        reply_markup=
            main_keyboard(),

        parse_mode="HTML",
    )


# =========================================================
# TUGMALAR
# =========================================================

@dp.message(
    F.text == "📊 Hisobot"
)
async def report_button(
    message: Message
):

    await send_report(message)


@dp.message(
    F.text == "💰 Balans"
)
async def balance_button(
    message: Message
):

    await send_balance(message)


@dp.message(
    F.text == "💳 Pul tarixi"
)
async def money_history_button(
    message: Message
):

    await send_money_history(message)


@dp.message(
    F.text == "📦 Yuk tarixi"
)
async def goods_history_button(
    message: Message
):

    await send_goods_history(message)


@dp.message(
    F.text == "🗄 Arxiv"
)
async def archive_button(
    message: Message
):

    await send_archive(message)


@dp.message(
    F.text == "📥 Excel"
)
async def excel_button(
    message: Message
):

    await export_excel(message)


# =========================================================
# ODDIY CHAT
# =========================================================

@dp.message()
async def smart_chat(
    message: Message,
    state: FSMContext
):

    text = (
        message.text or ""
    ).strip()

    current_state = await state.get_state()

    # Agar biror jarayon ichida bo‘lsa,
    # state handler ishlaydi.
    if current_state:
        return

    # =====================================================
    # AVVAL XARAJATNI TEKSHIRAMIZ
    # =====================================================

    parsed = parse_expense_text(
        text
    )

    if parsed:

        await add_transaction(

            user_id=
                message.from_user.id,

            transaction_type=
                "expense",

            total=
                parsed["total"],

            created_at=
                now(),

            product_name=
                parsed["product_name"],

            quantity=
                parsed["quantity"],

            unit=
                parsed["unit"],

            unit_price=
                parsed["unit_price"],

            category=
                "Yuk xaridi",
        )

        income, expense = await get_balance(
            message.from_user.id
        )

        balance = income - expense

        await message.answer(

            "📦 <b>YUK OLINDI</b>\n\n"

            f"📌 <b>"
            f"{html.escape(parsed['product_name'])}"
            f"</b>\n"

            f"⚖️ <b>"
            f"{qty(parsed['quantity'])} "
            f"{parsed['unit']}"
            f"</b>\n"

            f"💰 "
            f"{money(parsed['unit_price'])}"
            f" / {parsed['unit']}\n"

            f"🧮 <b>Jami: "
            f"{money(parsed['total'])}"
            f"</b>\n\n"

            f"🔴 Puldan ayrildi: "
            f"<b>-{money(parsed['total'])}</b>\n"

            f"💰 Qoldiq: "
            f"<b>{money(balance)}</b>\n\n"

            f"🕐 {now()}",

            reply_markup=
                main_keyboard(),

            parse_mode="HTML",
        )

        return

    # =====================================================
    # PUL KIRIMINI TEKSHIRAMIZ
    # =====================================================

    lowered = text.lower()

    income_words = [

        "qo‘shildi",
        "qoshildi",
        "keldi",
        "tushdi",
        "daromad",
        "kirim",
        "pul qo‘sh",
        "pul qosh",
    ]

    money_value = parse_money(
        text
    )

    if (
        money_value is not None
        and any(
            word in lowered
            for word in income_words
        )
    ):

        await add_transaction(

            user_id=
                message.from_user.id,

            transaction_type=
                "income",

            total=
                money_value,

            created_at=
                now(),

            category=
                "Daromad",
        )

        income, expense = await get_balance(
            message.from_user.id
        )

        balance = income - expense

        await message.answer(

            "🟢 <b>PUL KIRDI</b>\n\n"

            f"💰 <b>"
            f"+{money(money_value)}"
            f"</b>\n"

            f"💰 Qoldiq: "
            f"<b>{money(balance)}</b>\n"

            f"🕐 {now()}",

            reply_markup=
                main_keyboard(),

            parse_mode="HTML",
        )

        return

    # =====================================================
    # BUYRUQLAR
    # =====================================================

    command = detect_command(
        text
    )

    if command == "report":

        await send_report(
            message
        )

        return

    if command == "expense":

        await expense_button(
            message,
            state
        )

        return

    if command == "income":

        await income_button(
            message,
            state
        )

        return

    if command == "balance":

        await send_balance(
            message
        )

        return

    if command == "history":

        await send_money_history(
            message
        )

        return

    # =====================================================
    # TUSHUNILMAGAN MATN
    # =====================================================

    await message.answer(

        "🤔 <b>Bu gapni tushunmadim.</b>\n\n"

        "Masalan:\n\n"

        "📊 <i>menga hisobotni ber</i>\n"

        "➕ <i>xarajat qo‘sh</i>\n"

        "💵 <i>1000000 so‘m pul qo‘shildi</i>\n"

        "📦 <i>3 kg olma oldim 18000</i>\n"

        "💰 <i>balansimni ko‘rsat</i>",

        reply_markup=
            main_keyboard(),

        parse_mode="HTML",
    )


# =========================================================
# ISHGA TUSHIRISH
# =========================================================

async def main():

    await init_db()

    print(
        "🤖 Xarajat Hisob bot ishga tushdi..."
    )

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )