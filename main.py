import asyncio
import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import json
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
}


def clean_text(text):
    """Нормализует пробелы, сохраняя переводы строк."""
    if not text:
        return text
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    result = []
    prev_empty = False
    for line in lines:
        if not line:
            if not prev_empty:
                result.append("")
            prev_empty = True
        else:
            result.append(line)
            prev_empty = False
    return "\n".join(result).strip()


async def parse_search_page(session, params):
    url = "https://hh.ru/search/vacancy"
    try:
        async with session.get(url, params=params) as response:
            if response.status != 200:
                print(f"Ошибка поиска: {response.status}")
                return []
            text = await response.text()
    except Exception as e:
        print(f"Сетевая ошибка при поиске: {e}")
        return []

    soup = BeautifulSoup(text, "lxml")
    vacancies = []
    for card in soup.select('[data-qa="vacancy-serp__vacancy"]'):
        title_el = card.select_one('[data-qa="serp-item__title"]')
        company_el = card.select_one('[data-qa="vacancy-serp__vacancy-employer"]')
        salary_el = card.select_one('[data-qa="vacancy-serp__vacancy-compensation"]')
        if not title_el:
            continue

        href = title_el.get("href", "")
        clean_href = href.split("?")[0]
        absolute_url = urljoin("https://hh.ru", clean_href)

        vacancies.append({
            "name": clean_text(title_el.get_text(separator=" ", strip=True)),
            "url": absolute_url,
            "employer": clean_text(company_el.get_text(separator=" ", strip=True)) if company_el else None,
            "salary": clean_text(salary_el.get_text(separator=" ", strip=True)) if salary_el else None,
        })
    return vacancies


async def get_details(session, url):
    """Парсит страницу вакансии: описание, зарплату, ключевые навыки."""
    try:
        async with session.get(url) as response:
            if response.status != 200:
                return {}
            text = await response.text()
    except Exception as e:
        print(f"Ошибка при {url}: {e}")
        return {}

    soup = BeautifulSoup(text, "lxml")
    result = {}

    for sel in [
        '[data-qa="vacancy-description"]',
        '.vacancy-description',
        '[data-qa="vacancy-description-text"]',
    ]:
        desc_el = soup.select_one(sel)
        if desc_el:
            result["description"] = clean_text(desc_el.get_text(separator="\n", strip=True))
            break

    for sel in ['[data-qa="vacancy-salary"]', '[data-qa="vacancy-compensation"]']:
        sal_el = soup.select_one(sel)
        if sal_el:
            result["salary_detail"] = clean_text(sal_el.get_text(separator=" ", strip=True))
            break

    skills = [
        clean_text(el.get_text(separator=" ", strip=True))
        for el in soup.select('[data-qa="bloko-tag__text"]')
    ]
    if skills:
        result["skills"] = [s for s in skills if s]

    return result


async def main():
    params = {"text": "Python разработчик", "area": 1}
    all_vacancies = []

    async with aiohttp.ClientSession(headers=HEADERS) as session:

        for page in range(5):
            params["page"] = page
            print(f"Страница поиска {page}...")
            page_vacs = await parse_search_page(session, params)
            if not page_vacs:
                break
            all_vacancies.extend(page_vacs)
            await asyncio.sleep(2)

        print(f"Собрано ссылок: {len(all_vacancies)}")

        for i, vac in enumerate(all_vacancies):
            print(f"[{i + 1}/{len(all_vacancies)}] {vac['name']}")
            details = await get_details(session, vac["url"])
            vac.update(details)

            if not vac.get("salary") and details.get("salary_detail"):
                vac["salary"] = details["salary_detail"]
            vac.pop("salary_detail", None)

            await asyncio.sleep(1)

            if (i + 1) % 10 == 0:
                with open("vacancies.json", "w", encoding="utf-8") as f:
                    json.dump(all_vacancies, f, ensure_ascii=False, indent=2)

    with open("vacancies.json", "w", encoding="utf-8") as f:
        json.dump(all_vacancies, f, ensure_ascii=False, indent=2)

    desc_count = sum(1 for v in all_vacancies if v.get("description"))
    salary_count = sum(1 for v in all_vacancies if v.get("salary"))
    skills_count = sum(1 for v in all_vacancies if v.get("skills"))
    print(f"Готово: {len(all_vacancies)} вакансий")
    print(f"  с описанием: {desc_count}")
    print(f"  с зарплатой: {salary_count}")
    print(f"  со скиллами: {skills_count}")


if __name__ == "__main__":
    asyncio.run(main())