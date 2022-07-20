import json


def pretty(json_smth) -> str:
    return json.dumps(json_smth, indent=4)


def get_second_arg(*args, **kwargs):
    return args[1]

def parse_bignum(obj: dict) -> int:
    assert 'type' in obj and 'hex' in obj and obj['type'] == 'BigNumber'
    return int(obj['hex'], 16)
