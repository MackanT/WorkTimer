"""Where a user's things live (v6 Phase 6). User 1 — the single-user install —
keeps data/ exactly as before; every other user gets data/users/<key>/, so no
user's notes, backups or settings ever sit in another user's folder.

Browser-side preferences (app.storage.user) are keyed by the browser, not the
person — one browser can carry several people who sign in — so their keys are
the user's own too; user 1 keeps the plain keys, and with them its saved
preferences."""

from pathlib import Path

from .pg_connection import LOCAL_USER


def user_dir(data_dir, user_key: int) -> Path:
    """The user's own folder under `data_dir` (data/ itself for user 1)."""
    if isinstance(user_key, bool) or not isinstance(user_key, int) or user_key < 1:
        raise ValueError(f"a user's folder needs a user key (a positive int), not {user_key!r}")
    data_dir = Path(data_dir)
    return data_dir if user_key == LOCAL_USER else data_dir / "users" / str(user_key)


def pref_key(user_key: int, name: str) -> str:
    """The user's key for a preference in app.storage.user."""
    return name if user_key == LOCAL_USER else f"{name}@user{user_key}"
