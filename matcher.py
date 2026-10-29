import json
import os
import re
import hashlib
from pathlib import Path

import faiss
import numpy as np
from dotenv import load_dotenv
from gigachat import GigaChat
from sentence_transformers import SentenceTransformer

PROJECT_DIR = Path(__file__).parent
CERT_PATH = str(PROJECT_DIR / "russian_trusted_root_ca.crt")
MODEL = "GigaChat-2"

EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
INDEX_PATH = PROJECT_DIR / "faiss_index.bin"
INDEX_HASH_PATH = PROJECT_DIR / "faiss_index_hash.txt"
VACANCIES_PATH = PROJECT_DIR / "vacancies_analyzed.json"

load_dotenv(PROJECT_DIR / ".env.py")
GIGACHAT_KEY = os.getenv("GIGACHAT_KEY")
if not GIGACHAT_KEY:
    raise ValueError("GIGACHAT_KEY не найден в .env.py")

giga = GigaChat(
    credentials=GIGACHAT_KEY,
    scope="GIGACHAT_API_PERS",
    ca_bundle_file=CERT_PATH,
    verify_ssl_certs=True,
    model=MODEL,
    timeout=15
)

_embedder = None
_index = None
_vacancies = None

FALLBACK_MESSAGES = {
    "en": {
        "verdict": "Analysis unavailable",
        "summary": "The AI could not analyze this vacancy due to a temporary error.",
        "gaps": ["Temporary AI error"]
    },
    "ru": {
        "verdict": "Анализ недоступен",
        "summary": "ИИ не смог проанализировать вакансию из-за временной ошибки.",
        "gaps": ["Временная ошибка ИИ"]
    }
}


def _get_embedder():
    global _embedder
    if _embedder is None:
        print("Загружаю модель эмбеддингов...")
        _embedder = SentenceTransformer(EMBEDDING_MODEL)
    return _embedder


def _vacancy_text(v):
    parts = [v.get("name", "")]
    ai = v.get("ai_analysis") or {}
    if ai.get("stack"):
        parts.append("Стек: " + ", ".join(ai["stack"]))
    if ai.get("key_requirements"):
        parts.append("Требования: " + "; ".join(ai["key_requirements"]))
    if v.get("description"):
        parts.append(v["description"][:1000])
    return "\n".join(parts)


def get_file_hash(path):
    hasher = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def build_or_load_index():
    global _index, _vacancies

    if not VACANCIES_PATH.exists():
        print(f"⚠️ Файл {VACANCIES_PATH.name} не найден.")
        with open(VACANCIES_PATH, "w", encoding="utf-8") as f:
            json.dump([], f)
        _vacancies = []
        return

    with open(VACANCIES_PATH, "r", encoding="utf-8") as f:
        all_vacs = json.load(f)

    _vacancies = [v for v in all_vacs if v.get("description")]
    print(f"Вакансий в базе: {len(_vacancies)}")

    if not _vacancies:
        print("База пуста. Индекс не требуется.")
        return

    current_hash = get_file_hash(VACANCIES_PATH)

    if INDEX_PATH.exists() and INDEX_HASH_PATH.exists():
        saved_hash = INDEX_HASH_PATH.read_text(encoding="utf-8").strip()
        if current_hash == saved_hash:
            print("Загружаю FAISS-индекс с диска...")
            _index = faiss.read_index(str(INDEX_PATH))
            if _index.ntotal == len(_vacancies):
                print(f"  индекс валиден: {_index.ntotal} вакансий")
                return

    print("  перестраиваю индекс...")
    _index = None

    print("Строю эмбеддинги...")
    embedder = _get_embedder()
    texts = [_vacancy_text(v) for v in _vacancies]
    embeddings = embedder.encode(
        texts, show_progress_bar=True, normalize_embeddings=True
    ).astype("float32")

    _index = faiss.IndexFlatIP(embeddings.shape[1])
    _index.add(embeddings)
    faiss.write_index(_index, str(INDEX_PATH))
    INDEX_HASH_PATH.write_text(current_hash, encoding="utf-8")
    print(f"  индекс сохранён: {_index.ntotal} вакансий")


def find_top_vacancies(resume_text, top_k=10):
    if _index is None:
        raise RuntimeError("Сначала вызови build_or_load_index()")

    embedder = _get_embedder()
    query = embedder.encode([resume_text], normalize_embeddings=True).astype("float32")
    scores, indices = _index.search(query, top_k)

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0 or idx >= len(_vacancies):
            continue
        results.append({
            "vacancy": _vacancies[idx],
            "embedding_score": float(score),
        })
    return results


DEFAULT_LANGUAGE = "en"

PROMPTS = {
    "en": """You are a senior IT recruiter analyzing a candidate's fit for a job.

RESUME:
{resume}

VACANCY:
Title: {name}
Company: {employer}
Stack: {stack}
Requirements: {requirements}
Description: {description}

Return ONLY valid JSON (no markdown, no code fences):
{{
  "score": integer from 0 to 100,
  "translated_title": "translate the vacancy Title to English",
  "verdict": "one-sentence overall verdict (max 20 words)",
  "summary": "Write a detailed paragraph of EXACTLY 4-5 sentences. Explain the overall fit, explicitly mention specific technologies from the resume that match the vacancy, and summarize strengths and weaknesses.",
  "match_reasons": ["Provide exactly 3-4 detailed reasons why the candidate fits. Each reason must be a complete sentence mentioning specific skills."],
  "gaps": ["Provide exactly 2-3 detailed points explaining what the candidate is missing. Each point must be a complete sentence."]
}}

Scoring scale: 0-30 poor, 30-60 partial, 60-85 good, 85-100 excellent.
ALL text fields MUST be in ENGLISH. Stack entries stay in original form.
Return ONLY the JSON.""",

    "ru": """Ты — опытный IT-рекрутер. Сравни резюме кандидата и вакансию.

РЕЗЮМЕ:
{resume}

ВАКАНСИЯ:
Название: {name}
Компания: {employer}
Стек: {stack}
Требования: {requirements}
Описание: {description}

Верни ТОЛЬКО валидный JSON (без markdown и code fences):
{{
  "score": целое число от 0 до 100,
  "translated_title": "",
  "verdict": "одно предложение-вывод (макс 20 слов)",
  "summary": "Напиши подробный абзац ровно из 4-5 предложений. Объясни общее соответствие, обязательно упомяни конкретные технологии из резюме, которые совпадают с вакансией, и опиши сильные и слабые стороны.",
  "match_reasons": ["Дай ровно 3-4 подробные причины, почему кандидат подходит. Каждая причина должна быть полным предложением с упоминанием конкретных навыков."],
  "gaps": ["Дай ровно 2-3 подробных пункта, чего не хватает кандидату. Каждый пункт должен быть полным предложением."]
}}

Шкала: 0-30 не подходит, 30-60 частично, 60-85 хороший матч, 85-100 идеально.
ВСЕ текстовые поля — на РУССКОМ. Названия технологий — в оригинале.
Только JSON.""",
}


def extract_json(text):
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and start < end:
        return text[start:end + 1]
    return text


def validate_score_schema(data):
    if not isinstance(data, dict):
        return None

    try:
        data["score"] = int(data.get("score", 0))
    except (ValueError, TypeError):
        data["score"] = 0

    data["verdict"] = str(data.get("verdict", "")).strip()
    data["summary"] = str(data.get("summary", "")).strip()
    data["translated_title"] = str(data.get("translated_title", "")).strip()

    for field in ["match_reasons", "gaps"]:
        val = data.get(field, [])
        if not isinstance(val, list):
            val = [str(val)] if val else []
        data[field] = [str(v) for v in val]

    return data


def score_match(resume_text, vacancy, language=DEFAULT_LANGUAGE):
    ai = vacancy.get("ai_analysis") or {}
    template = PROMPTS.get(language, PROMPTS[DEFAULT_LANGUAGE])
    prompt = template.format(
        resume=resume_text[:3000],
        name=vacancy.get("name", ""),
        employer=vacancy.get("employer", ""),
        stack=", ".join(ai.get("stack", [])),
        requirements="; ".join(ai.get("key_requirements", [])),
        description=(vacancy.get("description") or "")[:2000],
    )
    try:
        response = giga.chat({
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 1500,
        })

        choices = getattr(response, "choices", None)
        if not choices:
            raise ValueError("Пустой ответ от GigaChat")

        first_choice = next(iter(choices), None)
        message = getattr(first_choice, "message", None)
        text = (getattr(message, "content", "") or "").strip()

        text = extract_json(text)
        raw_data = json.loads(text)
        return validate_score_schema(raw_data)

    except Exception as e:
        print(f"Scoring error: {e}")
        fallback = FALLBACK_MESSAGES.get(language, FALLBACK_MESSAGES["en"])
        return {
            "score": 0,
            "translated_title": "",
            "verdict": fallback["verdict"],
            "summary": fallback["summary"],
            "match_reasons": [],
            "gaps": fallback["gaps"]
        }
