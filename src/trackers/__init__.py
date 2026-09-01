"""Pluggable work-item tracker modules.

WorkTimer talks to issue trackers (Azure DevOps today; Jira etc. tomorrow)
through the `TrackerProvider` contract in `base.py`. Each provider module
implements it and registers itself in `registry.py` under a key; the customer
table's `integration_type` column names which provider a customer uses.

The canonical data shape is the work-item DataFrame (see
`base.WORK_ITEM_COLUMNS`): a provider that can produce it gets the board,
hierarchy, search and time-linking UI for free.

NOTE: provider modules are NOT imported here (azure imports src.devops, which
imports this package's registry — importing azure at package level would be a
cycle). `src/globals.py` imports the provider modules once at startup.
"""

from .base import (  # noqa: F401
    DEFAULT_TYPE_HIERARCHY,
    WORK_ITEM_COLUMNS,
    TrackerCapabilities,
    TrackerProvider,
)
from .registry import (  # noqa: F401
    available_providers,
    create_provider_for_row,
    get_provider_class,
    register_provider,
)
