"""
Schema Validation Script

This script validates the database schema and optionally applies migrations
to ensure the database matches the expected structure defined in database.py.

Usage:
    # Validate only (dry run):
    python scripts/validate_schema.py

    # Validate and auto-migrate:
    python scripts/validate_schema.py --migrate

    # Use specific database file:
    python scripts/validate_schema.py --db path/to/database.db --migrate
"""

import sys
import argparse
import logging
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from database import Database


class SimpleLogger:
    """Lightweight logger for standalone scripts."""

    def __init__(self, name, debug=False):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG if debug else logging.INFO)

        # Console handler
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG if debug else logging.INFO)
        formatter = logging.Formatter("%(levelname)s: %(message)s")
        handler.setFormatter(formatter)

        # Clear any existing handlers and add ours
        self.logger.handlers.clear()
        self.logger.addHandler(handler)

    def info(self, msg):
        self.logger.info(msg)

    def warning(self, msg):
        self.logger.warning(msg)

    def error(self, msg):
        self.logger.error(msg)


def main():
    parser = argparse.ArgumentParser(
        description="Validate and migrate WorkTimer database schema"
    )
    parser.add_argument(
        "--db",
        type=str,
        default="data/worktimer.db",
        help="Path to database file (default: data/worktimer.db)",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Automatically apply migrations to fix schema issues",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Setup logging
    log = SimpleLogger("SchemaValidator", debug=args.verbose)

    print("=" * 70)
    print("WorkTimer Database Schema Validation")
    print("=" * 70)
    print(f"Database: {args.db}")
    print(f"Auto-migrate: {'Yes' if args.migrate else 'No (dry run)'}")
    print("=" * 70)
    print()

    # Create database connection
    try:
        db = Database(args.db, log)
        print("✓ Database connection established")
    except Exception as e:
        print(f"✗ Failed to connect to database: {e}")
        return 1

    # Run validation
    print("\nValidating schema...")
    try:
        results = db.validate_and_migrate_schema(auto_migrate=args.migrate)
    except Exception as e:
        print(f"✗ Validation failed: {e}")
        return 1

    # Display results
    print()
    if results["errors"]:
        print("ERRORS:")
        for error in results["errors"]:
            print(f"  ✗ {error}")
        print()

    if results["missing_columns"]:
        if args.migrate:
            print("COLUMN MIGRATIONS APPLIED:")
            for migration in results["applied_migrations"]:
                if "column" in migration:
                    status = "✓ initialized" if migration["initialized"] else "✓ added"
                    print(f"  {status}: {migration['table']}.{migration['column']}")
        else:
            print("MISSING COLUMNS (dry run - not applied):")
            for missing in results["missing_columns"]:
                print(
                    f"  • {missing['table']}.{missing['column']} "
                    f"({missing['type']}, default={missing['default']})"
                )

    if results["missing_triggers"]:
        if args.migrate:
            print("\nTRIGGER MIGRATIONS APPLIED:")
            for migration in results["applied_migrations"]:
                if "trigger" in migration:
                    print(f"  ✓ created: {migration['trigger']}")
        else:
            print("\nMISSING TRIGGERS (dry run - not applied):")
            for trigger in results["missing_triggers"]:
                print(f"  • {trigger}")

    if not results["missing_columns"] and not results["missing_triggers"]:
        print("✓ Schema validation passed - database is up to date!")
    elif not args.migrate:
        print("\nRun with --migrate to apply these changes")

    print()
    print("=" * 70)

    # Summary
    total_issues = len(results["missing_columns"]) + len(results["missing_triggers"])
    if results["errors"]:
        print(f"Status: FAILED with {len(results['errors'])} errors")
        return 1
    elif total_issues > 0 and not args.migrate:
        print(f"Status: {total_issues} issues found (not fixed)")
        return 0
    elif results["applied_migrations"]:
        print(
            f"Status: SUCCESS - {len(results['applied_migrations'])} migrations applied"
        )
        return 0
    else:
        print("Status: SUCCESS - no changes needed")
        return 0


if __name__ == "__main__":
    sys.exit(main())
