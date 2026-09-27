"""Root pytest configuration — runs before anything imports NiceGUI.

NiceGUI reads NICEGUI_STORAGE_PATH once, when nicegui.storage is imported,
and its test fixtures clear that directory before and after every test —
deleting every storage-*.json in it. Left at the default (.nicegui/ in the
repo), a test run would wipe the app's real saved storage. So point it at a
throwaway directory here, first, and only then load NiceGUI's test plugin.

Anything that imports NiceGUI before this file runs — e.g. a plugin passed with
`-p` — defeats the redirect. tests/test_smoke_pages.py then refuses to run
rather than let NiceGUI clear the real directory.
"""

import os
import tempfile

os.environ["NICEGUI_STORAGE_PATH"] = tempfile.mkdtemp(prefix="worktimer-test-storage-")

pytest_plugins = ["nicegui.testing.user_plugin"]
