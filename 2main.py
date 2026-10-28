import json
import time
import re
import os
from gigachat import GigaChat
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env.py")

CERT_PATH = r"C:\Users\User\Downloads\russian_trusted_root_ca.crt"
GIGACHAT_KEY = os.getenv("GIGACHAT_KEY")
MODEL = "GigaChat-2"
INPUT_PATH = "vacancies.json"
OUTPUT_PATH = "vacancies_analyzed.json"

if not GIGACHAT_KEY:
    raise ValueError("GIGACHAT_KEY не найден.")
if not os.path.exists(CERT_PATH):
    raise FileNotFoundError(f"Сертификат не найден: {CERT_PATH}")

giga = GigaChat(
    credentials=GIGACHAT_KEY,
    scope="GIGACHAT_API_PERS",
    ca_bundle_file=CERT_PATH,
    verify_ssl_certs=True,
    model=MODEL,
)

PROMPT = """Ты — опытный IT-рекрутер. Проанализируй текст вакансии и верни ТОЛЬКО валидный JSON без markdown-обёрток, без комментариев и без пояснений.

Требования к полям:
- "stack": массив строк — конкретные технологии из текста вакансии. Только то, что реально упомянуто, не выдумывай.
- "grade": СТРОГО ОДНО значение из списка: "junior", "middle", "senior", "lead". Никаких других значений. Выбери наиболее подходящее по опыту и требованиям. Если неясно — "middle".
- "experience_years_min": целое число или null (если опыта не требуется — 0).
- "key_requirements": массив строк — 3-7 главных требований.
- "soft_skills": массив строк — софт-скиллы, если упомянуты, иначе пустой массив.
- "red_flags": массив строк — что может оттолкнуть кандидата. Если нет — пустой массив.

Пример:
{
  "stack": ["Python", "Django", "PostgreSQL"],
  "grade": "senior",
  "experience_years_min": 5,
  "key_requirements": ["опыт Python от 5 лет", "Django или FastAPI"],
  "soft_skills": ["самостоятельность"],
  "red_flags": ["офис в Москве"]
}

Верни ТОЛЬКО JSON. Ничего больше."""

VALID_GRADES = {"junior", "middle", "senior", "lead"}


def validate_schema(data):
    """Защита от кривого JSON от LLM."""
    if not isinstance(data, dict):
        return None

    stack = data.get("stack", [])
    if isinstance(stack, str):
        stack = [s.strip() for s in stack.split(",") if s.strip()]
    elif not isinstance(stack, list):
        stack = []
    data["stack"] = [str(s) for s in stack]

    grade = str(data.get("grade", "")).lower()
    data["grade"] = grade if grade in VALID_GRADES else "middle"

    exp = data.get("experience_years_min")
    if exp is not None:
        if not isinstance(exp, (int, float)):
            match = re.search(r"\d+", str(exp))
            if match:
                data["experience_years_min"] = int(match.group())
            else:
                data["experience_years_min"] = None
    else:
        data["experience_years_min"] = None

    for field in ["key_requirements", "soft_skills", "red_flags"]:
        val = data.get(field, [])
        if not isinstance(val, list):
            val = [str(val)] if val else []
        data[field] = [str(v) for v in val]

    return data


def extract_json(text):
    """Достает JSON из текста, даже если вокруг есть лишний текст."""
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and start < end:
        return text[start:end + 1]
    return text


def analyze_vacancy(description):
    if not description:
        return None
    try:
        response = giga.chat({
            "messages": [
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": description[:8000]}
            ],
            "temperature": 0.1,
            "max_tokens": 1000,
        })

        choices = getattr(response, "choices", None)
        if not choices:
            print("  Ошибка: GigaChat вернул пустой ответ.")
            return None

        first_choice = next(iter(choices), None)
        if first_choice is None:
            print("  Ошибка: не удалось извлечь choice.")
            return None

        message = getattr(first_choice, "message", None)
        if message is None:
            print("  Ошибка: в ответе GigaChat отсутствует message.")
            return None

        text = (getattr(message, "content", "") or "").strip()
        if not text:
            print("  Ошибка: GigaChat вернул пустой текст.")
            return None

        text = extract_json(text)
        raw_data = json.loads(text)
        return validate_schema(raw_data)

    except json.JSONDecodeError as e:
        print(f"  Ошибка парсинга JSON: {e}")
        return None
    except Exception as e:
        print(f"  Ошибка LLM: {e}")
        return None


def main():
    if os.path.exists(OUTPUT_PATH):
        print(f"Найден {OUTPUT_PATH}. Загружаю предыдущий прогресс...")
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            vacancies = json.load(f)
    else:
        with open(INPUT_PATH, "r", encoding="utf-8") as f:
            vacancies = json.load(f)

    total = len(vacancies)
    success = 0

    for i, vac in enumerate(vacancies):
        name = (vac.get("name") or "Без названия")[:60]

        if vac.get("ai_analysis") is not None:
            print(f"[{i + 1}/{total}] {name}... (уже обработано)")
            success += 1
            continue

        print(f"[{i + 1}/{total}] {name}...")
        analysis = analyze_vacancy(vac.get("description", ""))
        vac["ai_analysis"] = analysis

        if analysis:
            success += 1
            grade = analysis.get("grade")
            stack = analysis.get("stack", [])[:5]
            print(f"  → grade={grade}, stack={stack}")
        else:
            print(f"  → не удалось разобрать")

        if (i + 1) % 5 == 0 or (i + 1) == total:
            with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
                json.dump(vacancies, f, ensure_ascii=False, indent=2)
            print(f"  [Сохранено: {i + 1}/{total}]")

        time.sleep(2)

    print(f"\nГотово. Успешно проанализировано: {success}/{total}")
    print(f"Результат сохранён в {OUTPUT_PATH}")


if __name__ == "__main__":
    main()