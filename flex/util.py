import base64
from datetime import timedelta


def format_usd_amount(usd: float) -> str:
    return format(usd, ".2f")


def format_timedelta(td: timedelta) -> str:
    return f'{format(td.total_seconds(), ".1f")}s'


def decode_b64(str_b64: str | None) -> str | None:
    if str_b64 is None:
        return None

    bytes_repr = bytes(str_b64, encoding='utf-8')
    decoded_string = base64.b64decode(bytes_repr)
    return str(decoded_string, encoding='utf-8')


def build_key_str(func, *args, **kwargs) -> str:
    fn_name = getattr(func, '__qualname__', None) or getattr(func, '__name__', str(func))
    parts = [fn_name] + [str(a) for a in args]
    if kwargs:
        parts += [f'{k}={v}' for k, v in sorted(kwargs.items())]
    return ':'.join(parts)
