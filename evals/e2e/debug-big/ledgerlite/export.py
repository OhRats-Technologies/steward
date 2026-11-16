import json


def to_json(records):
    return json.dumps([{"date": d, "desc": s, "amount": float(a)} for d, s, a in records])
