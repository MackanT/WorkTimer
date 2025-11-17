#!/usr/bin/env python3
"""
Generate task_visuals.yml from template and existing data.

This script creates a task_visuals.yml file with:
1. Template structure from task_visuals.yml.template
2. Existing customer/project data from the database
3. Placeholder configurations for each found customer/project

Usage:
    python scripts/generate_task_visuals.py
"""

import os
import sys
import yaml
import sqlite3
from pathlib import Path

# Add the src directory to the path to import our modules
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))


def get_customers_and_projects(db_path):
    """Extract unique customers and projects from database"""
    customers = set()
    projects = set()

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Get customers from tasks table
        cursor.execute(
            "SELECT DISTINCT customer_name FROM tasks WHERE customer_name IS NOT NULL AND customer_name != ''"
        )
        for row in cursor.fetchall():
            if row[0]:
                customers.add(row[0])

        # Get projects from tasks table
        cursor.execute(
            "SELECT DISTINCT project_name FROM tasks WHERE project_name IS NOT NULL AND project_name != ''"
        )
        for row in cursor.fetchall():
            if row[0]:
                projects.add(row[0])

        # Also get from customers/projects tables if they exist
        try:
            cursor.execute(
                "SELECT DISTINCT customer_name FROM customers WHERE customer_name IS NOT NULL"
            )
            for row in cursor.fetchall():
                if row[0]:
                    customers.add(row[0])

            cursor.execute(
                "SELECT DISTINCT project_name FROM projects WHERE project_name IS NOT NULL"
            )
            for row in cursor.fetchall():
                if row[0]:
                    projects.add(row[0])
        except sqlite3.OperationalError:
            # Tables might not exist, that's ok
            pass

        conn.close()

    except Exception as e:
        print(f"Warning: Could not read database: {e}")

    return sorted(customers), sorted(projects)


def load_template():
    """Load the template file"""
    template_path = Path("config/task_visuals.yml.template")

    if not template_path.exists():
        print(f"Error: Template file {template_path} not found")
        return None

    try:
        with open(template_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading template: {e}")
        return None


def generate_config(customers, projects, template_data):
    """Generate the complete configuration"""

    # Start with template structure
    config = (
        template_data.copy()
        if template_data
        else {
            "visual": {
                "customers": {"default": {"icon": "group", "color": "blue-grey"}},
                "projects": {"default": {"icon": "folder", "color": "indigo"}},
            }
        }
    )

    # Icon suggestions for different types
    customer_icons = [
        "business",
        "apartment",
        "store",
        "factory",
        "domain",
        "account_balance",
        "corporate_fare",
    ]
    project_icons = [
        "code",
        "web",
        "mobile_friendly",
        "cloud",
        "storage",
        "analytics",
        "build",
        "settings",
    ]
    colors = [
        "red",
        "pink",
        "purple",
        "indigo",
        "blue",
        "light-blue",
        "cyan",
        "teal",
        "green",
        "light-green",
        "orange",
        "amber",
    ]

    # Add customers found in database
    if customers:
        print(f"Found {len(customers)} customers: {', '.join(customers)}")
        for i, customer in enumerate(customers):
            if customer not in config["visual"]["customers"]:
                icon = customer_icons[i % len(customer_icons)]
                color = colors[i % len(colors)]

                config["visual"]["customers"][customer] = {"icon": icon, "color": color}

    # Add projects found in database
    if projects:
        print(f"Found {len(projects)} projects: {', '.join(projects)}")
        for i, project in enumerate(projects):
            if project not in config["visual"]["projects"]:
                icon = project_icons[i % len(project_icons)]
                color = colors[(i + 3) % len(colors)]  # Offset to get different colors

                config["visual"]["projects"][project] = {"icon": icon, "color": color}

    return config


def main():
    """Main function"""

    # Check if we're in the right directory
    if not os.path.exists("config"):
        print("Error: Please run this script from the project root directory")
        return 1

    # Database path
    db_path = "worktimer.db"  # Default database name

    # Check for settings to get actual DB name
    settings_path = "config/config_settings.yml"
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = yaml.safe_load(f)
                db_path = settings.get("db_name", db_path)
        except Exception:
            pass

    print(f"Scanning database: {db_path}")

    # Get data from database
    customers, projects = get_customers_and_projects(db_path)

    # Load template
    template_data = load_template()

    # Generate configuration
    config = generate_config(customers, projects, template_data)

    # Output file
    output_path = Path("config/task_visuals.yml")

    # Check if file already exists
    if output_path.exists():
        response = input(f"{output_path} already exists. Overwrite? (y/N): ")
        if response.lower() != "y":
            print("Cancelled.")
            return 0

    # Write configuration
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("# Task Visual Customizations\n")
            f.write("# This file is generated from task_visuals.yml.template\n")
            f.write("# Customize the icons and colors below\n")
            f.write("# Icons: Material Design icon names (without 'md-' prefix)\n")
            f.write("# Colors: Quasar color names or hex codes\n\n")
            yaml.dump(
                config, f, default_flow_style=False, sort_keys=False, allow_unicode=True
            )

        print(f"Generated {output_path}")
        print("Customize the icons and colors as needed!")

        return 0

    except Exception as e:
        print(f"Error writing file: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
