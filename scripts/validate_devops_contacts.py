#!/usr/bin/env python3
"""
Validate the structure of config/devops_contacts.yml.

Usage:
    python validate_devops_contacts.py [--file PATH]

Exits with code 0 on success, non-zero on validation errors.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"ERROR: Failed to load YAML from {path}: {e}")
        raise


def validate_customer_entry(name: str, value: Any) -> list[str]:
    """Validate a single customer entry. Returns list of error messages."""
    errors: list[str] = []

    if not isinstance(value, dict):
        errors.append(
            f"customer '{name}': expected mapping, got {type(value).__name__}"
        )
        return errors

    # Expected keys in generator output
    contacts = value.get("contacts")
    assignees = value.get("assignees")

    if contacts is None:
        errors.append(f"customer '{name}': missing 'contacts' field")
    elif not isinstance(contacts, list):
        errors.append(f"customer '{name}': 'contacts' must be a list")

    if assignees is None:
        errors.append(f"customer '{name}': missing 'assignees' field")
    elif not isinstance(assignees, list):
        errors.append(f"customer '{name}': 'assignees' must be a list")

    # Optional field: default_assignee must be a string and must be present
    # in the assignees list (if assignees is valid).
    if "default_assignee" in value:
        da = value["default_assignee"]
        if not isinstance(da, str):
            errors.append(
                f"customer '{name}': 'default_assignee' must be a string if present"
            )
        else:
            # Only validate membership if assignees is a proper list
            if isinstance(assignees, list):
                if da not in assignees:
                    errors.append(
                        f"customer '{name}': 'default_assignee' value '{da}' not found in 'assignees' list"
                    )
            else:
                errors.append(
                    f"customer '{name}': cannot validate 'default_assignee' because 'assignees' is missing or not a list"
                )

    return errors


def validate_structure(cfg: Any) -> int:
    """Validate top-level structure and customer entries. Returns 0 on success, non-zero otherwise."""
    if cfg is None:
        print("ERROR: YAML file is empty")
        return 2

    if not isinstance(cfg, dict):
        print(f"ERROR: Top-level YAML must be a mapping/dict, got {type(cfg).__name__}")
        return 3

    customers = cfg.get("customers")
    if customers is None:
        print("ERROR: Missing top-level 'customers' key")
        return 4

    errors: list[str] = []

    # Generator currently produces a mapping: customers: { "Customer Name": { ... } }
    if isinstance(customers, dict):
        for name, value in customers.items():
            errors.extend(validate_customer_entry(name, value))
    elif isinstance(customers, list):
        # Support optional alternate format: list of customer objects
        for idx, item in enumerate(customers):
            if not isinstance(item, dict):
                errors.append(
                    f"customers[{idx}]: expected mapping, got {type(item).__name__}"
                )
                continue
            # try to infer name field
            name = (
                item.get("customer_id") or item.get("customer_name") or f"index_{idx}"
            )
            errors.extend(validate_customer_entry(name, item))
    else:
        print(
            f"ERROR: 'customers' must be a mapping or a list, got {type(customers).__name__}"
        )
        return 5

    if errors:
        print("Validation failed with the following errors:")
        for e in errors:
            print(f" - {e}")
        return 6

    # Minimal success summary
    total = len(customers) if isinstance(customers, dict) else len(customers)
    print(
        f"Validation OK: found {total} customer(s) and all required fields are present."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate devops contacts YAML")
    parser.add_argument(
        "--location",
        "-loc",
        default=Path("config") / "devops_contacts.yml",
        help="Location for final output, folder + file-name incl. '.yml'. Only use for testing - (default: config/devops_contacts.yml)",
    )
    args = parser.parse_args(argv)

    path = Path(args.location)
    if not path.exists():
        print(f"ERROR: File not found: {path}")
        return 10

    try:
        cfg = load_yaml(path)
    except Exception:
        return 11

    return validate_structure(cfg)


if __name__ == "__main__":
    rc = main()
    sys.exit(rc)
