import asyncio
import io
import os
from pathlib import Path

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from dotenv import load_dotenv

import matcher

PROJECT_DIR = Path(__file__).parent
load_dotenv(PROJECT_DIR / ".env.py")
BOT_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_PROXY_URL = os.getenv("TELEGRAM_PROXY_URL")

SUPPORTED_LANGS = ("en", "ru")
DEFAULT_LANG = "en"
DB_PATH = PROJECT_DIR / "users.db"
MAX_RESUME_LEN = 5000
TOP_K = 10
SCORE_TOP_N = 5

BTN_ABOUT_EN = "ℹ️ About"
BTN_ABOUT_RU = "ℹ️ О боте"

_user_langs = {}


async def init_db():
    global _user_langs
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, lang TEXT)")
        await db.commit()
        async with db.execute("SELECT user_id, lang FROM users") as cursor:
            async for row in cursor:
                _user_langs[row[0]] = row[1]


def get_lang(user_id: int) -> str:
    return _user_langs.get(str(user_id), DEFAULT_LANG)


async def set_lang(user_id: int, lang: str) -> None:
    if lang not in SUPPORTED_LANGS:
        return
    uid_str = str(user_id)
    _user_langs[uid_str] = lang
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO users (user_id, lang) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET lang = excluded.lang",
            (uid_str, lang),
        )
        await db.commit()


def t(user_id: int, key: str, **kwargs) -> str:
    text = UI[get_lang(user_id)][key]
    return text.format(**kwargs) if kwargs else text


UI = {
    "en": {
        "lang_set": "✅ Language set to English.",
        "start": (
            "<b>👋 Welcome to CV-scout!</b>\n\n"
            "I use AI to match your resume with real IT job vacancies.\n\n"
            "📥 <b>How to use:</b>\n"
            "• Send your resume as text\n"
            "• Or upload a PDF file\n"
            "• Or just click the button below to see an example"
        ),
        "menu_hint": "👇 Use the menu below to learn more. Send your resume to start!",
        "example_resume_title": "📄 <b>Testing with example resume:</b>\n\n",
        "example_resume_text": (
            "<b>Summary:</b>\n"
            "Python Developer with 3 years of commercial experience.\n\n"
            "<b>Stack:</b>\n"
            "Python 3.11, FastAPI, Django, PostgreSQL, Redis, Docker, Git.\n\n"
            "<b>Experience:</b>\n"
            "Developing REST APIs, integrations, writing tests (pytest).\n\n"
            "<b>Looking for:</b>\n"
            "Middle Python Developer position, remote or hybrid."
        ),
        "about_text": (
            "🤖 <b>CV-scout</b>\n\n"
            "<blockquote>An AI-powered Telegram bot that matches your resume with real IT job vacancies.</blockquote>\n\n"
            "🛠 <b>Tech stack:</b>\n"
            "• Python, Aiogram 3.x\n"
            "• GigaChat (LLM analysis)\n"
            "• Sentence-Transformers (embeddings)\n"
            "• FAISS (vector search)\n"
            "• BeautifulSoup (parsing)\n\n"
            "👨‍💻 <b>Author:</b> Kto_To106\n"
            "🔗 <b>GitHub:</b> https://github.com/KtoToProg/CV-scout-bot"
        ),
        "only_pdf": "Currently I only accept PDF. Send your resume as PDF or text.",
        "reading": "📄 Reading PDF...",
        "pdf_error": "Could not read PDF: {err}",
        "pdf_empty": "The PDF has almost no text. Please send your resume as text.",
        "too_short": "Resume is too short. Please send the full text or a PDF.",
        "analyzing": "🔍 <b>Analyzing your resume...</b>\nSearching for matches.",
        "search_error": "Search error: {err}",
        "nothing_found": "Nothing found. Try another resume.",
        "scoring": "🧠 <b>Scoring top-5 vacancies with AI...</b>\nThis will take 20–30 seconds.",
        "done": "✅ <b>Done! Here are your top matches:</b>\n",
        "score": "Score",
        "summary": "Summary",
        "strengths": "Strengths",
        "gaps": "Gaps",
        "no_company": "—",
        "semantic_verdict": "Based on semantic similarity",
    },
    "ru": {
        "lang_set": "✅ Язык переключён на русский.",
        "start": (
            "<b>👋 Привет! Это CV-scout</b>\n\n"
            "Я подбираю IT-вакансии под твоё резюме с помощью AI.\n\n"
            "📥 <b>Как пользоваться:</b>\n"
            "• Отправь резюме текстом\n"
            "• Или загрузи PDF-файл\n"
            "• Или нажми на кнопку ниже, чтобы посмотреть пример"
        ),
        "menu_hint": "👇 Используй меню внизу, чтобы узнать больше. Отправь резюме, чтобы начать!",
        "example_resume_title": "📄 <b>Тестирование на примере резюме:</b>\n\n",
        "example_resume_text": (
            "<b>О себе:</b>\n"
            "Python-разработчик, 3 года коммерческого опыта.\n\n"
            "<b>Стек:</b>\n"
            "Python 3.11, FastAPI, Django, PostgreSQL, Redis, Docker, Git.\n\n"
            "<b>Опыт:</b>\n"
            "Разработка REST API, интеграции, написание тестов (pytest).\n\n"
            "<b>Ищу:</b>\n"
            "Позицию middle Python-разработчика, удалённо или гибрид."
        ),
        "about_text": (
            "🤖 <b>CV-scout</b>\n\n"
            "<blockquote>AI-бот, который подбирает IT-вакансии под ваше резюме.</blockquote>\n\n"
            "🛠 <b>Технологии:</b>\n"
            "• Python, Aiogram 3.x\n"
            "• GigaChat (анализ LLM)\n"
            "• Sentence-Transformers (эмбеддинги)\n"
            "• FAISS (векторный поиск)\n"
            "• BeautifulSoup (парсинг)\n\n"
            "👨‍💻 <b>Автор:</b> Kto_To106\n"
            "🔗 <b>GitHub:</b> https://github.com/KtoToProg/CV-scout-bot"
        ),
        "only_pdf": "Пока принимаю только PDF. Отправь резюме в PDF или текстом.",
        "reading": "📄 Читаю PDF...",
        "pdf_error": "Не смог прочитать PDF: {err}",
        "pdf_empty": "В PDF почти нет текста. Отправь резюме текстом.",
        "too_short": "Резюме слишком короткое. Отправь полный текст или PDF.",
        "analyzing": "🔍 <b>Анализирую резюме...</b>\nИщу подходящие вакансии.",
        "search_error": "Ошибка поиска: {err}",
        "nothing_found": "Ничего не нашёл. Попробуй другое резюме.",
        "scoring": "🧠 <b>Оцениваю топ-5 вакансий через AI...</b>\nЭто займёт 20–30 секунд.",
        "done": "✅ <b>Готово! Лучшие вакансии:</b>\n",
        "score": "Очки",
        "summary": "Кратко",
        "strengths": "Почему подходит",
        "gaps": "Чего не хватает",
        "no_company": "—",
        "semantic_verdict": "На основе семантического сходства",
    },
}


def lang_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
        ],
        [
            InlineKeyboardButton(text="🚀 Try Example", callback_data="try_example")
        ]
    ])


def main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    lang = get_lang(user_id)
    label = BTN_ABOUT_RU if lang == "ru" else BTN_ABOUT_EN
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label)]],
        resize_keyboard=True,
        is_persistent=True,
    )


api_server = TelegramAPIServer.from_base(TELEGRAM_PROXY_URL)
session = AiohttpSession(api=api_server, timeout=30)
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher()


async def safe_answer(message: Message, text: str, **kwargs):
    for attempt in range(10):
        try:
            return await message.answer(text, **kwargs)
        except Exception as e:
            print(f"Сетевая ошибка при отправке (попытка {attempt+1}/10): {e}")
            if attempt < 9:
                await asyncio.sleep(3)


def format_report(scored, lang: str) -> str:
    L = UI[lang]
    v = scored["vacancy"]
    s = scored["score_data"] or {}

    display_name = v.get('name', '—')
    if lang == "en" and s.get("translated_title"):
        display_name = s["translated_title"]

    lines = [
        f"🎯 <b>{display_name}</b>",
        f"🏢 {v.get('employer', L['no_company'])}",
    ]
    if v.get("salary"):
        lines.append(f"💰 {v['salary']}")
    if v.get("url"):
        lines.append(f"🔗 {v['url']}")
    lines.append("")
    lines.append(f"📊 <b>{L['score']}: {s.get('score', '?')}/100</b>")

    if s.get("summary"):
        lines.append(f"\n<blockquote><b>{L['summary']}:</b> {s['summary']}</blockquote>")

    if s.get("match_reasons"):
        lines.append(f"\n✅ <b>{L['strengths']}:</b>")
        for r in s["match_reasons"][:4]:
            lines.append(f"• {r}")

    if s.get("gaps"):
        lines.append(f"\n⚠️ <b>{L['gaps']}:</b>")
        for g in s["gaps"][:3]:
            lines.append(f"• {g}")

    if s.get("verdict"):
        lines.append(f"\n💬 <i>{s['verdict']}</i>")

    return "\n".join(lines)


async def process_resume(message: Message, resume_text: str, lang: str):
    uid = message.from_user.id
    locked_lang = lang

    if len(resume_text) > MAX_RESUME_LEN:
        resume_text = resume_text[:MAX_RESUME_LEN]

    status_msg = await safe_answer(message, UI[locked_lang]["analyzing"], parse_mode="HTML")

    try:
        top = await asyncio.wait_for(
            asyncio.to_thread(matcher.find_top_vacancies, resume_text, SCORE_TOP_N),
            timeout=15.0
        )
    except Exception:
        err_text = "Поиск занял слишком много времени. Попробуйте еще раз." if locked_lang == "ru" else "Search took too long. Please try again."
        await status_msg.edit_text(err_text)
        return

    if not top:
        await status_msg.edit_text(UI[locked_lang]["nothing_found"])
        return

    print(f"🔍 FAISS вернул вакансий: {len(top)}")

    try:
        await status_msg.edit_text(UI[locked_lang]["scoring"], parse_mode="HTML")
    except Exception:
        pass

    scored = []
    for item in top:
        try:
            score_data = await asyncio.wait_for(
                asyncio.to_thread(matcher.score_match, resume_text, item["vacancy"], locked_lang),
                timeout=15.0
            )
            scored.append({**item, "score_data": score_data})
        except Exception:
            fallback_score = min(int(item.get("embedding_score", 0) * 100), 100)
            scored.append({
                **item,
                "score_data": {
                    "score": fallback_score,
                    "translated_title": "",
                    "verdict": UI[locked_lang]["semantic_verdict"],
                    "summary": "",
                    "match_reasons": [],
                    "gaps": []
                }
            })
        await asyncio.sleep(1)

    scored.sort(key=lambda x: (x.get("score_data") or {}).get("score", 0), reverse=True)

    try:
        await status_msg.edit_text(UI[locked_lang]["done"], parse_mode="HTML")
    except Exception:
        pass

    print(f"📤 Отправляю карточек: {len(scored)}")

    for i, item in enumerate(scored):
        report = format_report(item, locked_lang)
        await safe_answer(
            message,
            report,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        print(f"  Успешно отправлена {i+1}/{len(scored)}: {item['vacancy'].get('name', '')[:30]}...")
        await asyncio.sleep(2)


@dp.message(Command("start"))
async def cmd_start(message: Message):
    uid = message.from_user.id
    await safe_answer(
        message,
        t(uid, "start"),
        reply_markup=lang_keyboard(),
        parse_mode="HTML"
    )
    await safe_answer(
        message,
        t(uid, "menu_hint"),
        reply_markup=main_keyboard(uid)
    )


@dp.callback_query(F.data.startswith("lang:"))
async def cb_lang(callback: CallbackQuery):
    new_lang = callback.data.split(":", 1)[1]
    if new_lang not in SUPPORTED_LANGS:
        return

    uid = callback.from_user.id
    await set_lang(uid, new_lang)

    try:
        await callback.answer(t(uid, "lang_set"))
    except Exception:
        pass

    try:
        await callback.message.edit_text(
            t(uid, "start"),
            reply_markup=lang_keyboard(),
            parse_mode="HTML"
        )
    except Exception:
        pass

    try:
        await callback.message.answer(
            t(uid, "menu_hint"),
            reply_markup=main_keyboard(uid)
        )
    except Exception as e:
        print(f"Network error during lang change: {e}")


@dp.callback_query(F.data == "try_example")
async def cb_try_example(callback: CallbackQuery):
    try:
        await callback.answer()
    except Exception:
        pass
    uid = callback.from_user.id
    lang = get_lang(uid)

    resume_text = t(uid, "example_resume_text")
    example_text = t(uid, "example_resume_title") + f"<blockquote>{resume_text}</blockquote>"

    await safe_answer(callback.message, example_text, parse_mode="HTML")
    await process_resume(callback.message, resume_text, lang)


@dp.message(F.text.in_({BTN_ABOUT_EN, BTN_ABOUT_RU}))
async def handle_about(message: Message):
    uid = message.from_user.id
    await safe_answer(
        message,
        UI[get_lang(uid)]["about_text"],
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=main_keyboard(uid),
    )


@dp.message(F.document)
async def handle_pdf(message: Message):
    lang = get_lang(message.from_user.id)
    doc = message.document
    if not (doc.file_name or "").lower().endswith(".pdf"):
        await safe_answer(message, t(message.from_user.id, "only_pdf"))
        return

    msg = await safe_answer(message, t(message.from_user.id, "reading"))
    try:
        file_bytes = await bot.download(doc)
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes.read()))
        text = "\n".join(p.extract_text() or "" for p in reader.pages).strip()
    except Exception as e:
        await msg.edit_text(t(message.from_user.id, "pdf_error", err=e))
        return

    if len(text) < 50:
        await msg.edit_text(t(message.from_user.id, "pdf_empty"))
        return

    await process_resume(message, text, lang)


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message):
    if message.text in {BTN_ABOUT_EN, BTN_ABOUT_RU}:
        return

    lang = get_lang(message.from_user.id)
    text = message.text.strip()
    if len(text) < 50:
        await safe_answer(message, UI[lang]["too_short"])
        return
    await process_resume(message, text, lang)


async def main():
    await init_db()
    print("Building/loading vacancy index...")
    matcher.build_or_load_index()

    await bot.set_my_commands([
        BotCommand(command="start", description="Start / Начать"),
        BotCommand(command="about", description="About / О боте"),
    ])

    print("Starting bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
