import json


def pretty(json_smth) -> str:
    return json.dumps(json_smth, indent=4)
