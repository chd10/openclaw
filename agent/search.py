import re
import os
import pandas as pd

PRICE_PATH = "/app/data/price.xlsx"

STOPWORDS = {
    'телефон', 'маршрутизатор', 'коммутатор', 'шлюз', 'точка', 'доступа',
    'cisco', 'huawei', 'hp', 'hpe', 'juniper', 'fortinet', 'aruba', 'brocade', 'dell',
    'нужен', 'нужна', 'нужно', 'цена', 'на', 'стоимость', 'прайс', 'сколько',
    'стоит', 'найди', 'найдите', 'покажи', 'покажите', 'есть', 'ли', 'у',
    'вас', 'мне', 'нам', 'хочу', 'хотим', 'куплю', 'купим', 'по', 'для',
    'артикул', 'модель', 'модели', 'ip', 'voip',
}

# Matches typical part numbers: CP-8841-K9, WS-C2960-24TC-L, SFP-10G-SR, ASR-1001-X
_ARTICLE_RE = re.compile(r'\b[A-Za-z][A-Za-z0-9]*(?:[-\/][A-Za-z0-9]+){1,}\b')


def extract_article(query: str) -> str:
    matches = _ARTICLE_RE.findall(query)
    if matches:
        return matches[-1].upper()

    # Fallback: last non-stopword Latin token
    for token in reversed(query.strip().split()):
        t = re.sub(r'[.,!?:;]', '', token)
        if t and t.lower() not in STOPWORDS and re.match(r'^[A-Za-z0-9]+$', t) and len(t) >= 2:
            return t.upper()

    return query.strip()


def search_price(query: str) -> list[dict]:
    article = extract_article(query)
    if not os.path.exists(PRICE_PATH):
        return []

    df = pd.read_excel(PRICE_PATH, dtype=str).fillna('')
    article_upper = article.upper()

    results = []
    for _, row in df.iterrows():
        if any(article_upper in str(v).upper() for v in row.values):
            results.append({"article": article, "row": row.to_dict()})

    return results
