from datetime import date, timedelta
import re


def get_range_for(option):
    today = date.today()
    if option == "Day":
        return f"{today} - {today}"
    elif option == "Week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return f"{start} - {end}"
    elif option == "Month":
        start = today.replace(day=1)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month - timedelta(days=1)
        return f"{start} - {end}"
    elif option == "Year":
        start = today.replace(month=1, day=1)
        end = today.replace(month=12, day=31)
        return f"{start} - {end}"
    elif option == "All-Time":
        # Set to some default, or leave blank
        start = date(2000, 1, 1)  ## TODO min(start_date) in db
        end = today
        return f"{start} - {end}"
    else:
        return ""


def parse_date_range(date_range_str):
    # Accepts formats like 'YYYYMMDD - YYYYMMDD' or 'YYYY-MM-DD - YYYY-MM-DD'
    if not date_range_str:
        return None, None
    match = re.match(
        r"(\d{4}-?\d{2}-?\d{2})\s*-\s*(\d{4}-?\d{2}-?\d{2})", date_range_str
    )
    if match:
        start, end = match.groups()
        # Remove dashes if present
        start = start.replace("-", "")
        end = end.replace("-", "")
        return start, end
    return None, None
