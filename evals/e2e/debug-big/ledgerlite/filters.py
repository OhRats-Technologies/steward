from .util import norm


def by_category(records, category):
    """records: (date, desc, amount, category) tuples."""
    return [r for r in records if r[3] == norm(category)]
