"""
Time Tracking UI Module

Handles the time tracking interface with customer/project cards,
timer controls, and DevOps integration.
"""

from nicegui import ui
from ..helpers import UI_STYLES
import asyncio
from datetime import datetime
from .. import helpers
from ..globals import GlobalRegistry
from .dialogs import show_time_entry_dialog

# ============================================================================
# Constants
# ============================================================================

# UI Layout
GRID_COLUMNS = "160px 550px 240px"
TIME_OPTIONS = ["Day", "Week", "Month", "Year", "All-Time", "Custom"]
DISPLAY_OPTIONS = ["Time", "Bonus"]

# Project row grid layout
PROJECT_ROW_GRID = "20px 1fr 100px"
PROJECT_ROW_MIN_HEIGHT = "20px"

# Customer card sizing
CUSTOMER_CARD_FLEX = "flex:1 1 320px; min-width:320px; max-width:420px; margin:0 12px; box-sizing:border-box;"
CONTAINER_MAX_WIDTH = "1800px"

# ============================================================================
# Helper Functions
# ============================================================================


def is_time_display(display_value: str) -> bool:
    """Check if display mode is 'Time' (vs 'Bonus')."""
    return "time" in display_value.lower()


def format_value(value: float, is_time: bool) -> str:
    """Format a value as time (hours) or bonus (SEK)."""
    if is_time:
        return f"{value:.2f} h"
    return f"{value:.2f} SEK"


# ============================================================================
# Main UI
# ============================================================================


def ui_time_tracking():
    """
    Main time tracking UI with customer/project cards and timer controls.

    Features:
    - Time span selection (Day, Week, Month, Year, All-Time, Custom)
    - Display options (Time or Bonus amounts)
    - Customer/Project cards with checkboxes for timer control
    - DevOps integration for saving work comments
    """
    # Get global instances
    LOG = GlobalRegistry.get("LOG")
    QE = GlobalRegistry.get("QE")
    DO = GlobalRegistry.get("DO")
    run_async_task = GlobalRegistry.get("run_async_task")
    update_tab_indicator_now = GlobalRegistry.get("update_tab_indicator_now")

    with ui.grid(columns=GRID_COLUMNS).classes("w-full gap-0 items-center"):
        ui.label("Time Span").classes("items-center")
        selected_time = (
            ui.radio(TIME_OPTIONS, value="Day").props("inline").classes("items-center")
        )
        with ui.input("Date range").classes(
            f"{UI_STYLES.get_widget_width('compact')} ml-4 items-center"
        ) as date_input:
            with ui.menu().props("no-parent-event") as menu:
                date_picker = (
                    ui.date()
                    .props("range")
                    .bind_value(
                        date_input,
                        forward=lambda x: f"{x['from']} - {x['to']}"
                        if isinstance(x, dict) and x
                        else x
                        if isinstance(x, str)
                        else None,
                        backward=lambda x: {
                            "from": x.split(" - ")[0],
                            "to": x.split(" - ")[1],
                        }
                        if " - " in (x or "")
                        else None,
                    )
                )
                with ui.row().classes("justify-end"):
                    ui.button("Close", on_click=menu.close).props("flat")
            with date_input.add_slot("append"):
                ui.icon("edit_calendar").on("click", menu.open).classes(
                    "cursor-pointer items-center"
                )

        ui.label("Display Options").classes("mr-8 items-center")
        radio_display_selection = (
            ui.radio(DISPLAY_OPTIONS, value="Time")
            .props("inline")
            .classes("items-center")
        )

    ui.separator().classes("my-2")

    def set_custom_radio(e):
        LOG.log_msg("DEBUG", f"Date picker selected: {date_input.value}")
        selected_time.value = "Custom"
        asyncio.create_task(update_ui())

    def on_radio_time_change(e):
        LOG.log_msg("DEBUG", f"Radio Date selected: {selected_time.value}")
        date_input.value = helpers.get_range_for(selected_time.value)
        asyncio.create_task(update_ui())

    def on_radio_type_change(e):
        LOG.log_msg("DEBUG", f"Radio Type selected: {radio_display_selection.value}")
        asyncio.create_task(update_ui())

    date_input.value = helpers.get_range_for(selected_time.value)
    date_input.on("update:model-value", set_custom_radio)
    date_picker.on("update:model-value", set_custom_radio)
    selected_time.on("update:model-value", on_radio_time_change)
    radio_display_selection.on("update:model-value", on_radio_type_change)

    container = ui.element()
    ignore_next_checkbox_event = False

    async def on_checkbox_change(event, checked, customer_id, project_id):
        """
        Handle checkbox change for time/project row. If checked, insert row; if unchecked, show popup for comment/devops/delete.
        """
        nonlocal ignore_next_checkbox_event
        if ignore_next_checkbox_event:
            ignore_next_checkbox_event = False
            return

        if checked:
            run_async_task(
                lambda: asyncio.run(
                    QE.function_db("insert_time_row", int(customer_id), int(project_id))
                )
            )
            # Update tab indicator immediately when starting a timer
            asyncio.create_task(update_tab_indicator_now())
            return

        # Unchecked - show dialog for saving comment/DevOps
        checkbox = event.sender

        async def handle_save(git_id_val, comment, store_to_devops):
            """Save time entry with comment and optionally to DevOps."""
            run_async_task(
                lambda: asyncio.run(
                    QE.function_db(
                        "insert_time_row",
                        int(customer_id),
                        int(project_id),
                        git_id=git_id_val,
                        comment=comment,
                    )
                )
            )

            # Save to DevOps if requested
            if store_to_devops and git_id_val and git_id_val > 0:
                sql_code = f"select customer_name from customers where customer_id = {customer_id}"
                customer_name = await QE.query_db(sql_code)
                if DO.manager:
                    status, msg = DO.manager.save_comment(
                        customer_name=customer_name.iloc[0]["customer_name"],
                        comment=comment,
                        git_id=git_id_val,
                    )
                    col = "positive" if status else "negative"
                    ui.notify(msg, color=col)

            await update_tab_indicator_now()

        async def handle_delete():
            """Delete the time entry."""
            await QE.function_db("delete_time_row", int(customer_id), int(project_id))
            await update_tab_indicator_now()

        def handle_close():
            """Close dialog without saving - reset checkbox."""
            nonlocal ignore_next_checkbox_event
            ignore_next_checkbox_event = True
            checkbox.set_value(True)

        await show_time_entry_dialog(
            customer_id=customer_id,
            project_id=project_id,
            on_save_callback=handle_save,
            on_delete_callback=handle_delete,
            on_close_callback=handle_close,
        )

    def make_callback(customer_id, project_id):
        return lambda e: on_checkbox_change(e, e.value, customer_id, project_id)

    value_labels = []
    customer_total_labels = []

    async def get_ui_data():
        date_range_str = date_input.value
        start_date, end_date = helpers.parse_date_range(date_range_str)
        if not start_date or not end_date:  # Fallback to today if not set
            today = datetime.now().strftime("%Y%m%d")
            start_date = end_date = today
        df = await QE.function_db(
            "get_customer_ui_list", start_date=start_date, end_date=end_date
        )
        return df

    async def render_ui():
        """Render the main time tracking UI, grouped by customer and project."""
        value_labels.clear()
        customer_total_labels.clear()
        df = await get_ui_data()
        container.clear()

        def get_total_string(customer_id):
            is_time = is_time_display(radio_display_selection.value)
            total = df[df["customer_id"] == customer_id][
                "total_time" if is_time else "user_bonus"
            ].sum()
            return format_value(total, is_time)

        async def make_project_row(project, customer_id):
            sql_query = (
                f"select * from time where customer_id = {customer_id} "
                f"and project_id = {project['project_id']} and end_time is null"
            )
            df_counts = await QE.query_db(sql_query)
            initial_state = bool(len(df_counts) > 0)

            with (
                ui.row()
                .classes("items-center w-full")
                .style(
                    f"display: grid; grid-template-columns: {PROJECT_ROW_GRID}; "
                    f"align-items: center; margin-bottom:2px; min-height:{PROJECT_ROW_MIN_HEIGHT};"
                )
            ):
                ui.checkbox(
                    on_change=make_callback(
                        project["customer_id"], project["project_id"]
                    ),
                    value=initial_state,
                )
                ui.label(str(project["project_name"])).classes("ml-2 truncate")
                is_time = is_time_display(radio_display_selection.value)
                value = project["total_time"] if is_time else project["user_bonus"]
                total_string = format_value(value, is_time)
                value_label = (
                    ui.label(f"{total_string}")
                    .classes("text-grey text-right whitespace-nowrap w-full")
                    .style("max-width:100px; overflow-x:auto;")
                )
                value_labels.append((value_label, customer_id, project["project_id"]))

        async def make_customer_card(customer_id, customer_name, group):
            with ui.card().classes(UI_STYLES.get_card_classes("xs", "card_padded")):
                with ui.column().classes("items-start").style(CUSTOMER_CARD_FLEX):
                    total_string = get_total_string(customer_id)
                    with (
                        ui.row()
                        .classes("w-full justify-between")
                        .style("display:flex; align-items:center;")
                    ):
                        ui.label(str(customer_name)).classes("text-lg text-right")
                        label_total = ui.label(total_string).classes(
                            "text-base text-grey text-right"
                        )
                        customer_total_labels.append((label_total, customer_id))
                    for _, project in group.iterrows():
                        await make_project_row(project, customer_id)

        customers = df.groupby(["customer_id", "customer_name"])
        with container:
            with (
                ui.row()
                .classes("px-4 justify-between overflow-x-auto")
                .style(
                    f"flex-wrap:nowrap; width:100%; max-width:{CONTAINER_MAX_WIDTH}; margin:0 auto;"
                )
            ):
                # Run customer cards in series for UI consistency
                for (customer_id, customer_name), group in customers:
                    await make_customer_card(customer_id, customer_name, group)

    async def update_ui():
        """Update the UI labels for project and customer totals based on the latest data."""
        if selected_time.value != "Custom":
            expected_range = helpers.get_range_for(selected_time.value)
            if date_input.value != expected_range:
                date_input.value = expected_range

        df = await get_ui_data()
        is_time = is_time_display(radio_display_selection.value)

        def get_time_string(row):
            value = row["total_time"] if is_time else row["user_bonus"]
            return format_value(value, is_time)

        # Build a lookup for (customer_id, project_id) to row
        df_lookup = {
            (row["customer_id"], row["project_id"]): row for _, row in df.iterrows()
        }

        # Update project value labels
        for value_label, customer_id, project_id in value_labels:
            row = df_lookup.get((customer_id, project_id))
            if row is not None:
                value_label.text = get_time_string(row)

        # Update customer total labels
        for label_total, customer_id in customer_total_labels:
            total = df[df["customer_id"] == customer_id][
                "total_time" if is_time else "user_bonus"
            ].sum()
            label_total.text = format_value(total, is_time)

    # Register these functions globally so they can be accessed by other UI components
    GlobalRegistry.set("time_tracking_render_ui", render_ui)
    GlobalRegistry.set("time_tracking_update_ui", update_ui)

    asyncio.run(render_ui())
