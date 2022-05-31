import json


def pretty(json_smth) -> str:
    return json.dumps(json_smth, indent=4)


def get_second_arg(*args, **kwargs):
    return args[1]
