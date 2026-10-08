import json

DEFAULT_REVIEWS = [dict(name='Cath Gertie Mitchell', rating=5,
    text='Top quality work, the kids loved it. Excellent communication and customer service too. Would definitely recommend :)',
    detail='5th birthday party · 23 August 2026')]


def read_reviews(value):
    try:
        rows = json.loads(value)
        if not isinstance(rows, list) or len(rows) > 10:
            return DEFAULT_REVIEWS
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not isinstance(row.get('text'), str) or not isinstance(row.get('detail'), str) or type(row.get('rating')) is not int or not 1 <= row['rating'] <= 5:
                return DEFAULT_REVIEWS
        return rows
    except (ValueError, TypeError):
        return DEFAULT_REVIEWS


def validate_reviews(form):
    reviews = []
    for index in range(10):
        name = form.get(f'review_name_{index}', '').strip()
        text = form.get(f'review_text_{index}', '').strip()
        detail = form.get(f'review_detail_{index}', '').strip()
        if not name and not text and not detail:
            continue
        if not name or not text:
            raise ValueError('Each review needs a reviewer name and review text.')
        if len(name) > 100 or len(text) > 1000 or len(detail) > 160:
            raise ValueError('Keep review names under 101 characters, text under 1001 and details under 161.')
        try:
            rating = int(form.get(f'review_rating_{index}', '5'))
        except ValueError:
            raise ValueError('Choose a rating between 1 and 5.')
        if not 1 <= rating <= 5:
            raise ValueError('Choose a rating between 1 and 5.')
        reviews.append(dict(name=name, text=text, detail=detail, rating=rating))
    return json.dumps(reviews, ensure_ascii=False)
