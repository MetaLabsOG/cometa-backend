# copy-paste from https://stackoverflow.com/a/13756038/7700373
def seconds_format(s: float):
    seconds = int(s)
    periods = [
        ('год', 'года',      60*60*24*365),
        ('месяц', 'месяца',  60*60*24*30),
        ('день', 'дней',     60*60*24),
        ('час', 'часа',      60*60),
        ('минута', 'минут',  60),
        ('секунда', 'секунд', 1)
    ]

    strings = []
    for period_name, periods_name, period_seconds in periods:
        if seconds > period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            name = periods_name if period_value > 1 else period_name
            return f'{period_value} {name}'

            # TODO: remove return to have more details
            # strings.append(f'{period_value} {name}')

    return ", ".join(strings)


def td_format(td_object):
    seconds = int(td_object.total_seconds())
    return seconds_format(seconds)


def usd_format(usd: float) -> str:
    return format(usd, ".2f")
