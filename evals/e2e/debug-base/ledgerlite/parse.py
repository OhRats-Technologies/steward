def parse(text):
    """Return a list of (date, description, amount_str) from CSV text."""
    rows = []
    for line in text.strip().splitlines():
        date, desc, amount = line.split(",")
        rows.append((date, desc, amount))
    return rows
