"""Available Pages"""

from .time_tracking import time_tracking_page
from .add_data import add_data_page
from .board import board_page
from .query_editor import query_editor_page
from .log import log_page
from .info import info_page
from .tasks import tasks_page
from .settings import settings_page
from .notepad import notepad_page
from .root import root_page

__all__ = [
    "root_page",
    "time_tracking_page",
    "add_data_page",
    "board_page",
    "query_editor_page",
    "tasks_page",
    "notepad_page",
    "log_page",
    "info_page",
    "settings_page",
]  # list of pages to expose
