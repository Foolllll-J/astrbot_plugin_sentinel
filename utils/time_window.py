import re
from datetime import datetime, timedelta
from typing import Any


WEEKDAY_ALIASES = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def parse_time_range_bounds(time_range: str) -> tuple[int, int] | None:
    if not isinstance(time_range, str):
        return None
    m = re.fullmatch(r"\s*([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)\s*", time_range)
    if not m:
        return None
    start_min = int(m.group(1)) * 60 + int(m.group(2))
    end_min = int(m.group(3)) * 60 + int(m.group(4))
    return start_min, end_min


def parse_weekdays(expr: str) -> set[int] | None:
    if not expr:
        return None
    days: set[int] = set()
    parts = [p.strip().lower() for p in str(expr).split(",") if p.strip()]
    if not parts:
        return None

    for part in parts:
        if "-" in part:
            left, right = [x.strip().lower() for x in part.split("-", 1)]
            if left not in WEEKDAY_ALIASES or right not in WEEKDAY_ALIASES:
                return None
            start = WEEKDAY_ALIASES[left]
            end = WEEKDAY_ALIASES[right]
            if start <= end:
                days.update(range(start, end + 1))
            else:
                days.update(range(start, 7))
                days.update(range(0, end + 1))
            continue
        if part not in WEEKDAY_ALIASES:
            return None
        days.add(WEEKDAY_ALIASES[part])

    return days


def parse_active_when_date(expr: str) -> dict | None:
    text = str(expr).strip()
    if not text:
        return None

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(~\d{4}-\d{2}-\d{2})?", text):
        if "~" in text:
            left, right = [x.strip() for x in text.split("~", 1)]
        else:
            left = right = text
        try:
            start_date = datetime.strptime(left, "%Y-%m-%d").date()
            end_date = datetime.strptime(right, "%Y-%m-%d").date()
        except Exception:
            return None
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        return {"kind": "full", "start": start_date, "end": end_date}

    if re.fullmatch(r"\d{2}-\d{2}(~\d{2}-\d{2})?", text):
        if "~" in text:
            left, right = [x.strip() for x in text.split("~", 1)]
        else:
            left = right = text
        try:
            sm, sd = [int(x) for x in left.split("-", 1)]
            em, ed = [int(x) for x in right.split("-", 1)]
            datetime(2000, sm, sd)
            datetime(2000, em, ed)
        except Exception:
            return None
        return {"kind": "md", "start": (sm, sd), "end": (em, ed)}

    if re.fullmatch(r"\d{1,2}(~\d{1,2})?", text):
        if "~" in text:
            left, right = [x.strip() for x in text.split("~", 1)]
        else:
            left = right = text
        try:
            sd = int(left)
            ed = int(right)
        except Exception:
            return None
        if sd < 1 or sd > 31 or ed < 1 or ed > 31:
            return None
        return {"kind": "d", "start": sd, "end": ed}

    return None


def parse_active_when(active_when: str) -> tuple[dict | None, str | None]:
    text = str(active_when or "").strip()
    if not text:
        return None, None

    parts = [p.strip() for p in text.split() if p.strip()]
    if not parts:
        return None, None

    spec: dict[str, Any] = {}
    for part in parts:
        if ":" in part and "-" in part:
            if "time_range" in spec:
                return None, f"time_range 重复时间段: {part}"
            bounds = parse_time_range_bounds(part)
            if not bounds:
                return None, f"time_range 时间段格式错误: {part}"
            spec["time_range"] = part
            spec["_time_bounds"] = bounds
            continue

        if part[0].isdigit():
            if "date_spec" in spec:
                return None, f"time_range 重复日期片段: {part}"
            date_spec = parse_active_when_date(part)
            if not date_spec:
                return None, f"time_range 日期格式错误: {part}"
            spec["date_spec"] = date_spec
            continue

        if "weekdays" in spec:
            return None, f"time_range 重复星期片段: {part}"
        weekdays = parse_weekdays(part)
        if weekdays is None:
            return None, f"time_range 星期格式错误: {part}"
        spec["weekdays"] = weekdays

    return spec, None


def match_date_spec(date_spec: dict, anchor_date) -> bool:
    kind = date_spec.get("kind")
    if kind == "full":
        start = date_spec.get("start")
        end = date_spec.get("end")
        return start <= anchor_date <= end
    if kind == "md":
        md = (anchor_date.month, anchor_date.day)
        start = tuple(date_spec.get("start", (0, 0)))
        end = tuple(date_spec.get("end", (0, 0)))
        if start <= end:
            return start <= md <= end
        return md >= start or md <= end
    if kind == "d":
        d = anchor_date.day
        start = int(date_spec.get("start", 0))
        end = int(date_spec.get("end", 0))
        if start <= end:
            return start <= d <= end
        return d >= start or d <= end
    return True


def is_in_active_when(spec: dict) -> bool:
    if not spec:
        return True

    now_dt = datetime.now()
    now_date = now_dt.date()
    now_weekday = now_dt.weekday()
    now_minute = now_dt.hour * 60 + now_dt.minute

    time_bounds = spec.get("_time_bounds")
    anchor_date = now_date
    anchor_weekday = now_weekday

    if isinstance(time_bounds, tuple):
        start_min, end_min = time_bounds
        cross_day = start_min > end_min
        if not cross_day:
            if not (start_min <= now_minute <= end_min):
                return False
        else:
            if not (now_minute >= start_min or now_minute <= end_min):
                return False
            if now_minute <= end_min:
                prev = now_dt - timedelta(days=1)
                anchor_date = prev.date()
                anchor_weekday = prev.weekday()

    date_spec = spec.get("date_spec")
    if isinstance(date_spec, dict):
        if not match_date_spec(date_spec, anchor_date):
            return False

    weekdays = spec.get("weekdays")
    if isinstance(weekdays, set) and weekdays:
        if anchor_weekday not in weekdays:
            return False

    return True
