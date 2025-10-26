#!/usr/bin/env python3
"""
Generate devops_contacts.yml from existing database data.

This script helps bootstrap the devops_contacts.yml file by extracting
customer names from the database and creating a template structure.

Usage:
    python generate_devops_contacts.py

The script will:
1. Read customer names from the database
2. Create/update config/devops_contacts.yml with customer entries
3. Preserve any existing contact/assignee data
"""

import yaml
import sqlite3
from pathlib import Path

# Configuration
DB_PATH = "data_dpg.db"  # Update if your DB has a different name
CONFIG_FOLDER = "config"
OUTPUT_FILE = f"{CONFIG_FOLDER}/devops_contacts.yml"


def get_customers_from_db(db_path):
    """Extract active customer names from the database."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Get all active customers
        cursor.execute("""
            SELECT DISTINCT customer_name 
            FROM customers 
            WHERE is_current = 1
            ORDER BY customer_name
        """)

        customers = [row[0] for row in cursor.fetchall()]
        conn.close()

        return customers
    except Exception as e:
        print(f"Error reading database: {e}")
        return []


def load_existing_config(file_path):
    """Load existing config if it exists."""
    if Path(file_path).exists():
        with open(file_path, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def generate_config(customers, existing_config=None):
    """Generate the config structure."""
    if existing_config is None:
        existing_config = {}

    config = {
        "# NOTE": "Add this file to .gitignore to keep contact data private",
        "customers": existing_config.get("customers", {}),
        "default": existing_config.get(
            "default", {"contacts": [], "assignees": ["unassigned"]}
        ),
    }

    # Add new customers that don't exist yet
    for customer in customers:
        if customer not in config["customers"]:
            config["customers"][customer] = {
                "contacts": ["# Add contact person names here", "# Example: John Doe"],
                "assignees": [
                    "# Add assignee email addresses here",
                    "# Example: developer@company.com",
                ],
                "default_assignee": "# The default assignee for this customer (optional)",
            }
            print(f"  + Added new customer: {customer}")
        else:
            print(f"  ✓ Customer exists: {customer}")

    return config


def save_config(config, file_path):
    """Save config to YAML file."""
    with open(file_path, "w") as f:
        yaml.dump(
            config, f, default_flow_style=False, sort_keys=False, allow_unicode=True
        )


def main():
    print("DevOps Contacts Generator")
    print("=" * 50)

    # Get customers from database
    print(f"\n1. Reading customers from {DB_PATH}...")
    customers = get_customers_from_db(DB_PATH)

    if not customers:
        print("   ⚠ No customers found in database!")
        return

    print(f"   Found {len(customers)} customer(s)")

    # Load existing config
    print(f"\n2. Loading existing config from {OUTPUT_FILE}...")
    existing_config = load_existing_config(OUTPUT_FILE)

    if existing_config:
        print(
            f"   Found existing config with {len(existing_config.get('customers', {}))} customer(s)"
        )
    else:
        print("   No existing config found, creating new one")

    # Generate config
    print("\n3. Generating config...")
    config = generate_config(customers, existing_config)

    # Save config
    print(f"\n4. Saving to {OUTPUT_FILE}...")
    save_config(config, OUTPUT_FILE)

    print("\n" + "=" * 50)
    print("✓ Complete!")
    print("\nNext steps:")
    print(f"1. Edit {OUTPUT_FILE}")
    print("2. Replace comment placeholders with actual contact names and emails")
    print(f"3. Add {OUTPUT_FILE.split('/')[-1]} to .gitignore if not already there")
    print("\nExample entry:")
    print("  customers:")
    print('    "Customer Name":')
    print("      contacts:")
    print('        - "John Doe"')
    print('        - "Jane Smith"')
    print("      assignees:")
    print('        - "dev1@company.com"')
    print('        - "dev2@company.com"')


if __name__ == "__main__":
    main()
