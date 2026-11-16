def total(amounts):
    """Sum amount strings; return a string with two decimals."""
    s = 0.0
    for a in amounts:
        s += float(a)
    return f"{round(s, 2):.2f}"
