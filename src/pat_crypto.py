"""PAT-token encryption at rest.

Customer PAT tokens live in the customers table, which travels with every
backup. This module encrypts them with Fernet (symmetric, from the
`cryptography` package) using a key auto-generated on first use as
`.pat_key` NEXT TO the database file. `Database.backup_to()` copies only
the DB via SQLite's backup API, so the key never travels with a backup —
a restored backup on another machine has unreadable tokens by design:
re-enter the PATs there (the log says so explicitly).

Format: encrypted values carry the ``enc:`` prefix. Anything without it is
plaintext — accepted everywhere and migrated once at startup by
``Database.initialize_db()``. If `cryptography` is not installed, the module
degrades to plaintext passthrough with a loud log line instead of crashing.
"""

import os
import threading

try:
    from cryptography.fernet import Fernet
except ImportError:  # degrade to plaintext, never crash the app
    Fernet = None

ENC_PREFIX = "enc:"

# One Fernet per key file — the key is read/created once per process.
_fernets: dict = {}
_lock = threading.Lock()


def encryption_available() -> bool:
    return Fernet is not None


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(ENC_PREFIX)


def _key_path_for(db_file: str) -> str | None:
    """The key lives next to the DB. In-memory/URI databases have no
    directory to put a key in — encryption is skipped for those."""
    if not db_file or db_file == ":memory:" or db_file.startswith("file:"):
        return None
    return os.path.join(
        os.path.dirname(os.path.abspath(db_file)), ".pat_key"
    )


def _fernet_for(db_file: str, log):
    key_path = _key_path_for(db_file)
    if Fernet is None or key_path is None:
        return None
    with _lock:
        if key_path in _fernets:
            return _fernets[key_path]
        try:
            if os.path.exists(key_path):
                with open(key_path, "rb") as f:
                    key = f.read().strip()
            else:
                key = Fernet.generate_key()
                with open(key_path, "wb") as f:
                    f.write(key)
                log.info(f"Generated PAT encryption key at {key_path}")
            fernet = Fernet(key)
        except Exception as e:
            log.error(f"PAT encryption unavailable ({key_path}): {e}")
            fernet = None
        _fernets[key_path] = fernet
        return fernet


def encrypt_pat(value, db_file: str, log) -> str:
    """Encrypt a plaintext PAT to 'enc:...'. Idempotent: empty values and
    already-encrypted values pass through unchanged; so does everything when
    encryption is unavailable (missing package or in-memory DB)."""
    if not value or is_encrypted(value):
        return value
    fernet = _fernet_for(db_file, log)
    if fernet is None:
        if Fernet is None:
            log.warning(
                "cryptography not installed — storing PAT token in plaintext. "
                "Install it (uv sync) to encrypt tokens at rest."
            )
        return value
    return ENC_PREFIX + fernet.encrypt(str(value).encode("utf-8")).decode("ascii")


def decrypt_pat(value, db_file: str, log) -> str:
    """Decrypt an 'enc:...' value; plaintext passes through. A value that
    cannot be decrypted (typically a backup restored without its .pat_key)
    yields '' so the customer is skipped with a clear log instead of the
    tracker seeing garbage credentials."""
    if not value or not is_encrypted(value):
        return value
    fernet = _fernet_for(db_file, log)
    if fernet is None:
        log.error(
            "Found an encrypted PAT token but no usable encryption key — "
            "re-enter the PAT for this customer (keys do not travel with "
            "backups)."
        )
        return ""
    try:
        return fernet.decrypt(value[len(ENC_PREFIX):].encode("ascii")).decode(
            "utf-8"
        )
    except Exception:
        log.error(
            "Could not decrypt a stored PAT token (wrong or regenerated "
            ".pat_key — typically a backup restored on another machine). "
            "Re-enter the PAT for this customer."
        )
        return ""
