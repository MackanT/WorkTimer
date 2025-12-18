"""
Database Tools UI Module

Provides database management tools:
- Schema comparison between databases
- SQL query runner on uploaded databases
- Schema validation and migration
"""

import os
import sqlite3
import tempfile

from nicegui import events, ui

from .. import helpers
from ..database import Database
from ..globals import GlobalRegistry


def build_database_compare_tab(main_db_name: str):
    """
    Build the database schema comparison tab.

    Allows users to upload a .db file and see SQL to sync it with the main database.

    Args:
        main_db_name: Name of the main database file to compare against
    """
    UI_STYLES = helpers.UI_STYLES

    def handle_upload(e: events.UploadEventArguments):
        ui.notify(f"File uploaded: {e.name}", color="positive")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            tmp.write(e.content.read())
            uploaded_path = tmp.name

        sync_sql = Database.generate_sync_sql(main_db_name, uploaded_path)
        db_deltas.set_content(sync_sql)
        db_deltas.update()
        os.remove(uploaded_path)  # Clean up temp file

    with ui.card().classes(
        UI_STYLES.get_card_classes("xs", "card").replace("mx-auto", "ml-0")
    ):
        ui.label("Upload a .db file to compare with the main database.").classes(
            UI_STYLES.get_layout_classes("title").replace("mb-4", "mb-0 dense")
        )
        ui.upload(on_upload=handle_upload).props("accept=.db").classes(
            "q-pa-xs q-ma-xs"
        )
        ui.separator().classes("my-4")
        ui.label("SQL to synchronize uploaded DB:").classes(
            UI_STYLES.get_layout_classes("subtitle")
        )
        db_deltas = (
            ui.code("--temp location of sql-changes...", language="sql")
            .props("readonly")
            .classes(UI_STYLES.get_widget_style("code_display", "large")["classes"])
        )


def build_database_update_tab():
    """
    Build the database update/SQL runner tab.

    Allows users to upload a .db file, run SQL queries on it, and download the modified database.
    """
    UI_STYLES = helpers.UI_STYLES
    QE = GlobalRegistry.get("QE")

    uploaded_db_path = None
    original_db_filename = None

    async def validate_main_schema():
        """Validate the main database schema and optionally migrate it."""
        result_box.set_content("Running schema validation...")
        result_box.update()

        try:
            results = await QE.function_db(
                "validate_and_migrate_schema", auto_migrate=auto_migrate_switch.value
            )

            # Format results
            output = []
            output.append("=" * 70)
            output.append("SCHEMA VALIDATION RESULTS")
            output.append("=" * 70)
            output.append(
                f"Auto-migrate: {'ON' if auto_migrate_switch.value else 'OFF (dry run)'}"
            )
            output.append("")

            if results["missing_columns"]:
                output.append("Missing Columns:")
                for col in results["missing_columns"]:
                    output.append(
                        f"  • {col['table']}.{col['column']} ({col['type']}, default={col['default']})"
                    )
                output.append("")

            if results["missing_triggers"]:
                output.append("Missing Triggers:")
                for trigger in results["missing_triggers"]:
                    output.append(f"  • {trigger}")
                output.append("")

            if results["applied_migrations"]:
                output.append("Applied Migrations:")
                for mig in results["applied_migrations"]:
                    if "column" in mig:
                        status = "initialized" if mig["initialized"] else "added"
                        output.append(f"  ✓ {status}: {mig['table']}.{mig['column']}")
                    elif "trigger" in mig:
                        output.append(f"  ✓ created trigger: {mig['trigger']}")
                output.append("")

            if results["errors"]:
                output.append("ERRORS:")
                for error in results["errors"]:
                    output.append(f"  ✗ {error}")
                output.append("")

            total_issues = len(results["missing_columns"]) + len(
                results["missing_triggers"]
            )
            if total_issues == 0:
                output.append("✓ Schema validation passed - database is up to date!")
                ui.notify("Schema is up to date!", type="positive")
            elif results["applied_migrations"]:
                output.append(
                    f"✓ Schema migration complete: {len(results['applied_migrations'])} changes applied"
                )
                ui.notify(
                    f"{len(results['applied_migrations'])} migrations applied",
                    type="positive",
                )
            else:
                output.append(
                    f"Schema validation found {total_issues} issues (not fixed - dry run mode)"
                )
                ui.notify(f"{total_issues} issues found", type="warning")

            output.append("=" * 70)
            result_box.set_content("\\n".join(output))
            result_box.update()

        except Exception as e:
            error_msg = f"Error during validation: {e}"
            result_box.set_content(error_msg)
            result_box.update()
            ui.notify(error_msg, type="negative")

    def handle_upload(e: events.UploadEventArguments):
        nonlocal uploaded_db_path, original_db_filename
        ui.notify(f"File uploaded: {e.name}", color="positive")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            tmp.write(e.content.read())
            uploaded_db_path = tmp.name
            original_db_filename = e.name if hasattr(e, "name") else "database.db"
        result_box.set_content(f"-- Uploaded DB: {uploaded_db_path}")
        result_box.update()

    def run_sql():
        if not uploaded_db_path:
            ui.notify("No uploaded DB!", color="negative")
            return

        try:
            conn = sqlite3.connect(uploaded_db_path)
            cursor = conn.cursor()
            query = sql_input.value if hasattr(sql_input, "value") else sql_input.text
            cursor.executescript(query)
            conn.commit()

            # Try to fetch results if it's a SELECT
            if query.strip().lower().startswith("select"):
                cursor.execute(query)
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                result = (
                    "\t".join(columns)
                    + "\n"
                    + "\n".join(["\t".join(str(cell) for cell in row) for row in rows])
                )
            else:
                result = "Query executed successfully."
                ui.notify("Query executed successfully.", color="positive")
            conn.close()
            result_box.set_content(result)
            result_box.update()
        except Exception as e:
            result_box.set_content(f"Error: {e}")
            result_box.update()

    def download_db():
        if not uploaded_db_path:
            ui.notify("No uploaded DB!", color="negative")
            return
        # Serve the file for download with the original filename
        filename = (
            original_db_filename
            if original_db_filename
            else os.path.basename(uploaded_db_path)
        )
        ui.download(uploaded_db_path, filename)

    # Schema Validation Section
    with ui.card().classes(
        UI_STYLES.get_card_classes("xs", "card").replace("mx-auto", "ml-0")
    ):
        ui.label("Schema Validation & Migration").classes(
            UI_STYLES.get_layout_classes("title").replace("mb-4", "mb-2 dense")
        )
        ui.label(
            "Validate the main database schema against expected structure"
        ).classes("text-sm text-gray-400 mb-2")
        with ui.row().classes("w-full items-center gap-3 mb-2"):
            ui.label("Auto-migrate").classes("text-sm")
            auto_migrate_switch = ui.switch(value=False)
            ui.label("(Apply fixes automatically)").classes("text-xs text-gray-400")
        ui.button(
            "Validate Schema", icon="check_circle", on_click=validate_main_schema
        ).props("color=primary")

    # SQL Runner Section
    with ui.card().classes(
        UI_STYLES.get_card_classes("xs", "card").replace("mx-auto", "ml-0")
    ):
        ui.label("Upload a .db file to run SQL queries on.").classes(
            UI_STYLES.get_layout_classes("title").replace("mb-4", "mb-0 dense")
        )
        ui.upload(on_upload=handle_upload).props("accept=.db").classes(
            "q-pa-xs q-ma-xs mb-2"
        )
        with ui.row().classes("w-full mb-2"):
            ui.button("Run SQL", on_click=run_sql).classes("mr-2")
            ui.button("Download DB", on_click=download_db)

    sql_input = ui.codemirror(
        "-- Enter SQL query here --",
        language="SQLite",
        theme="dracula",
    ).classes(UI_STYLES.get_widget_style("code_display", "small")["classes"])

    result_box = ui.code("-- Results will appear here --", language="sql").classes(
        UI_STYLES.get_widget_style("code_display", "medium")["classes"]
    )
