"""Provider registry: integration_type key → TrackerProvider class.

Provider modules call `register_provider(cls)` at import time; the manager
resolves each customer's provider from the customers table's
`integration_type` column via `create_provider_for_row`.
"""

DEFAULT_PROVIDER_KEY = "devops"

_providers: dict = {}


def register_provider(cls):
    """Register a TrackerProvider subclass under its `provider_key`. Usable as
    a decorator. Re-registering the same key overwrites (supports reload)."""
    key = getattr(cls, "provider_key", "")
    if not key:
        raise ValueError(f"{cls.__name__} has no provider_key")
    _providers[key] = cls
    return cls


def get_provider_class(key):
    """The provider class registered under `key`, or None."""
    return _providers.get(key)


def available_providers() -> list:
    """Registered provider keys."""
    return sorted(_providers)


def create_provider_for_row(row, log):
    """Build an (unconnected) provider for one customers-table row.

    Resolves the class from the row's `integration_type` (missing/empty →
    the default "devops" for backwards compatibility), then delegates to the
    class's `from_customer_row`. Returns None — with a log line — when the
    type is unknown or the row lacks the provider's required credentials.
    """
    raw = row.get("integration_type") if hasattr(row, "get") else None
    key = str(raw).strip().lower() if raw and str(raw).strip() else DEFAULT_PROVIDER_KEY
    cls = _providers.get(key)
    if cls is None:
        log.warning(
            f"Unknown integration_type '{key}' for customer "
            f"'{row.get('customer_name', '?')}' — skipping "
            f"(registered: {available_providers()})"
        )
        return None
    return cls.from_customer_row(row, log)
