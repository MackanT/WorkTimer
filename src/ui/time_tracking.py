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

# ============================================================================
# Helper Functions
# ============================================================================


def is_time_display(display_value: str) -> bool:
    """Check if display mode is 'Time' (vs 'Bonus')."""
    return "time" in display_value.lower()


def format_value(value: float, is_time: bool) -> str:
    """Format a value as time (hours) or bonus (SEK)."""
    return f"{value:.2f} h" if is_time else f"{value:.2f} SEK"


def get_column_name(is_time: bool) -> str:
    """Get the appropriate column name based on display mode."""
    return "total_time" if is_time else "user_bonus"


def create_date_range_picker(on_change_callback) -> tuple:
    """
    Create date range input with calendar picker.

    Returns:
        Tuple of (date_input, date_picker) widgets
    """
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
            with ui.row().classes(UI_STYLES.get_layout_classes("row_end")):
                ui.button("Close", on_click=menu.close).props("flat")
        with date_input.add_slot("append"):
            ui.icon("edit_calendar").on("click", menu.open).classes(
                "cursor-pointer items-center"
            )

    # Bind change events
    date_input.on("update:model-value", on_change_callback)
    date_picker.on("update:model-value", on_change_callback)

    return date_input, date_picker


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
    QE = GlobalRegistry.get("QE")
    DO = GlobalRegistry.get("DO")
    run_async_task = GlobalRegistry.get("run_async_task")
    update_tab_indicator_now = GlobalRegistry.get("update_tab_indicator_now")

    # State for checkbox event handling
    ignore_next_checkbox_event = False

    # ========================================================================
    # UI Control Handlers
    # ========================================================================

    def set_custom_radio(e):
        """Set time span to Custom when date picker changes."""
        selected_time.value = "Custom"
        asyncio.create_task(update_ui())

    def on_radio_time_change(e):
        """Update date range when time span radio changes."""
        date_input.value = helpers.get_range_for(selected_time.value)
        asyncio.create_task(update_ui())

    def on_radio_type_change(e):
        """Refresh UI when display type changes (Time/Bonus)."""
        asyncio.create_task(update_ui())

    # ========================================================================
    # Filter Controls
    # ========================================================================

    with ui.grid(columns=GRID_COLUMNS).classes(UI_STYLES.get_layout_classes("full_row_nogap")):
        ui.label("Time Span").classes(UI_STYLES.get_layout_classes("row_centered"))
        selected_time = (
            ui.radio(TIME_OPTIONS, value="Day").props("inline").classes(UI_STYLES.get_layout_classes("row_centered"))
        )
        date_input, date_picker = create_date_range_picker(set_custom_radio)

        ui.label("Display Options").classes("mr-8 items-center")
        radio_display_selection = (
            ui.radio(DISPLAY_OPTIONS, value="Time")
            .props("inline")
            .classes(UI_STYLES.get_layout_classes("row_centered"))
        )

    ui.separator().classes(UI_STYLES.get_layout_classes("margin_y_2"))

    # Wire up event handlers
    date_input.value = helpers.get_range_for(selected_time.value)
    selected_time.on("update:model-value", on_radio_time_change)
    radio_display_selection.on("update:model-value", on_radio_type_change)

    container = ui.element()

    # ========================================================================
    # Checkbox Event Handling
    # ========================================================================

    async def on_checkbox_change(event, checked, customer_id, project_id):
        """
        Handle checkbox change for time/project row.
        If checked, insert row; if unchecked, show popup for comment/devops/delete.
        """
        nonlocal ignore_next_checkbox_event
        if ignore_next_checkbox_event:
            ignore_next_checkbox_event = False
            return

        # Convert IDs to int once
        customer_id_int = int(customer_id)
        project_id_int = int(project_id)

        if checked:
            run_async_task(
                lambda: asyncio.run(
                    QE.function_db("insert_time_row", customer_id_int, project_id_int)
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
                        customer_id_int,
                        project_id_int,
                        git_id=git_id_val,
                        comment=comment,
                    )
                )
            )

            # Save to DevOps if requested
            if store_to_devops and git_id_val and git_id_val > 0:
                customer_name_df = await QE.query_db(
                    "select customer_name from customers where customer_id = ?",
                    params=(customer_id_int,),
                )
                if DO.manager and not customer_name_df.empty:
                    status, msg = DO.manager.save_comment(
                        customer_name=customer_name_df.iloc[0]["customer_name"],
                        comment=comment,
                        git_id=git_id_val,
                    )
                    col = "positive" if status else "negative"
                    ui.notify(msg, color=col)

            await update_tab_indicator_now()

        async def handle_delete():
            """Delete the time entry."""
            await QE.function_db("delete_time_row", customer_id_int, project_id_int)
            await update_tab_indicator_now()

        def handle_close():
            """Close dialog without saving - reset checkbox."""
            nonlocal ignore_next_checkbox_event
            ignore_next_checkbox_event = True
            checkbox.set_value(True)

        await show_time_entry_dialog(
            customer_id=customer_id_int,
            project_id=project_id_int,
            on_save_callback=handle_save,
            on_delete_callback=handle_delete,
            on_close_callback=handle_close,
        )

    def make_callback(customer_id, project_id):
        return lambda e: on_checkbox_change(e, e.value, customer_id, project_id)

    value_labels = []
    customer_total_labels = []

    async def get_ui_data():
        """Fetch UI data for the selected date range."""
        date_range_str = date_input.value
        start_date, end_date = helpers.parse_date_range(date_range_str)

        # Fallback to today if date range not set
        if not start_date or not end_date:
            today = datetime.now().strftime("%Y%m%d")
            start_date = end_date = today

        return await QE.function_db(
            "get_customer_ui_list", start_date=start_date, end_date=end_date
        )

    async def render_ui():
        """Render the main time tracking UI, grouped by customer and project."""
        value_labels.clear()
        customer_total_labels.clear()
        df = await get_ui_data()
        container.clear()

        # Cache display mode to avoid repeated calls
        is_time = is_time_display(radio_display_selection.value)
        column_name = get_column_name(is_time)

        def get_total_string(customer_id):
            """Get formatted total for a customer."""
            total = df[df["customer_id"] == customer_id][column_name].sum()
            return format_value(total, is_time)

        async def make_project_row(project, customer_id):
            """Create a single project row with checkbox and value."""
            sql_query = (
                f"select * from time where customer_id = {customer_id} "
                f"and project_id = {project['project_id']} and end_time is null"
            )
            df_counts = await QE.query_db(sql_query)
            initial_state = bool(len(df_counts) > 0)

            with (
                ui.row()
                .classes(UI_STYLES.get_layout_classes("time_tracking_project_row"))
                .style(UI_STYLES.get_inline_style("time_tracking", "project_row"))
            ):
                ui.checkbox(
                    on_change=make_callback(
                        project["customer_id"], project["project_id"]
                    ),
                    value=initial_state,
                )
                ui.label(str(project["project_name"])).classes(
                    UI_STYLES.get_widget_style("time_tracking_project_name")["classes"]
                )

                # Use cached column_name instead of recalculating
                value = project[column_name]
                total_string = format_value(value, is_time)

                project_value_style = UI_STYLES.get_widget_style(
                    "time_tracking_project_value"
                )
                value_label = (
                    ui.label(f"{total_string}")
                    .classes(project_value_style["classes"])
                    .style(project_value_style.get("style", ""))
                )
                value_labels.append((value_label, customer_id, project["project_id"]))

        async def make_customer_card(customer_id, customer_name, group):
            """Create a customer card with all its projects."""
            with ui.card().classes(UI_STYLES.get_card_classes("xs", "card_padded")):
                with (
                    ui.column()
                    .classes(
                        UI_STYLES.get_layout_classes("time_tracking_customer_column")
                    )
                    .style(UI_STYLES.get_inline_style("time_tracking", "customer_card"))
                ):
                    total_string = get_total_string(customer_id)
                    with (
                        ui.row()
                        .classes(
                            UI_STYLES.get_layout_classes(
                                "time_tracking_customer_header"
                            )
                        )
                        .style(
                            UI_STYLES.get_inline_style(
                                "time_tracking", "customer_header"
                            )
                        )
                    ):
                        ui.label(str(customer_name)).classes(
                            UI_STYLES.get_widget_style("time_tracking_customer_name")[
                                "classes"
                            ]
                        )
                        label_total = ui.label(total_string).classes(
                            UI_STYLES.get_widget_style("time_tracking_customer_total")[
                                "classes"
                            ]
                        )
                        customer_total_labels.append((label_total, customer_id))
                    for _, project in group.iterrows():
                        await make_project_row(project, customer_id)

        customers = df.groupby(["customer_id", "customer_name"])
        with container:
            with (
                ui.row()
                .classes(UI_STYLES.get_layout_classes("time_tracking_container"))
                .style(UI_STYLES.get_inline_style("time_tracking", "container"))
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
        column_name = get_column_name(is_time)

        # Build a lookup for (customer_id, project_id) to row
        df_lookup = {
            (row["customer_id"], row["project_id"]): row for _, row in df.iterrows()
        }

        # Update project value labels
        for value_label, customer_id, project_id in value_labels:
            row = df_lookup.get((customer_id, project_id))
            if row is not None:
                value = row[column_name]
                value_label.text = format_value(value, is_time)

        # Update customer total labels
        for label_total, customer_id in customer_total_labels:
            total = df[df["customer_id"] == customer_id][column_name].sum()
            label_total.text = format_value(total, is_time)

    # Register these functions globally so they can be accessed by other UI components
    GlobalRegistry.set("time_tracking_render_ui", render_ui)
    GlobalRegistry.set("time_tracking_update_ui", update_ui)

    asyncio.run(render_ui())
