import calendar

from .money import total


def month_total(records, month):
    year, mon = map(int, month.split("-"))
    last = calendar.monthrange(year, mon)[1]
    days = {f"{month}-{d:02d}" for d in range(1, last)}
    return total(a for d, _, a in records if d in days)
