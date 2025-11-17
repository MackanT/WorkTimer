"""
UI Module - WorkTimer

This module contains all UI-related functions split by feature area:
- time_tracking.py - Time tracking UI with customer/project cards
- add_data.py - Data input forms for customers, projects, bonuses, DevOps
- tasks.py - Task management UI with cards and table views
- query_editor.py - SQL query editor with save/update/delete
- utils.py - Log viewer and info/README viewer

All UI functions are re-exported here for backward compatibility.
"""

from .time_tracking import ui_time_tracking
from .add_data import ui_add_data
from .tasks import ui_tasks
from .query_editor import ui_query_editor
from .utils import ui_log, ui_info

__all__ = [
    'ui_time_tracking',
    'ui_add_data',
    'ui_tasks',
    'ui_query_editor',
    'ui_log',
    'ui_info',
]
