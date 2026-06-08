from datetime import datetime, time, timedelta

from django.utils import timezone


def local_day_bounds(day):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    return start, start + timedelta(days=1)


def local_month_bounds(month_date):
    month_start = month_date.replace(day=1)
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(month_start, time.min), tz)
    end = timezone.make_aware(datetime.combine(next_month, time.min), tz)
    return start, end
