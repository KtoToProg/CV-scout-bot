import json
import matcher


def main():
    matcher.build_or_load_index()

    resume = """
    Python-разработчик, 3 года коммерческого опыта.
    Стек: Python 3.11, FastAPI, Django, PostgreSQL, Redis, Docker, Git, Linux.
    Опыт: разработка REST API, интеграции с внешними сервисами, написание тестов (pytest).
    Soft skills: самостоятельность, работа в команде, code review.
    Ищу позицию middle Python-разработчика, удалённо или гибрид.
    """

    print("\n=== Топ-5 по эмбеддингам ===")
    results = matcher.find_top_vacancies(resume, top_k=5)

    if not results:
        print("Не найдено ни одной вакансии.")
        return

    for r in results:
        print(f"{r['embedding_score']:.3f} — {r['vacancy']['name']} @ {r['vacancy'].get('employer')}")

    print("\n=== GigaChat-скоринг первой ===")
    score = matcher.score_match(resume, results[0]["vacancy"])

    print(json.dumps(score, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()