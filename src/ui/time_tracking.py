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
    update_tab_indicator_now = GlobalRegistry.get("update_tab_indicator_now")

    # State for checkbox event handling
    ignore_next_checkbox_event = False

    # State for sort order editing
    edit_mode = {"enabled": False}
    customer_order = []  # Will store (customer_id, customer_name) tuples
    project_orders = {}  # Will store {customer_id: [(project_id, project_name), ...]}

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

    async def toggle_edit_mode():
        """Toggle between normal and edit mode for sorting."""
        edit_mode["enabled"] = not edit_mode["enabled"]
        edit_button.props(f"color={'primary' if edit_mode['enabled'] else 'default'}")
        if edit_mode["enabled"]:
            edit_button.set_text("Save Order")
            ui.notify("Edit mode: Use ↑↓ arrows to reorder", type="info")
        else:
            # Save sort order to database
            try:
                await QE.function_db("save_sort_order", customer_order, project_orders)
                edit_button.set_text("Edit Order")
                ui.notify("Sort order saved successfully!", type="positive")
            except Exception as e:
                LOG = GlobalRegistry.get("LOG")
                if LOG:
                    LOG.error(f"Error saving sort order: {e}")
                edit_button.set_text("Edit Order")
                ui.notify("Error saving sort order", type="negative")
        await render_ui()

    # ========================================================================
    # Filter Controls
    # ========================================================================

    # Top row: Time span controls on left, Edit Order button on right
    with ui.row().classes("w-full justify-between items-center gap-4"):
        # Left side: Time span controls
        with ui.row().classes("items-center gap-4"):
            ui.label("Time Span").classes("items-center")
            selected_time = (
                ui.radio(TIME_OPTIONS, value="Day")
                .props("inline")
                .classes("items-center")
            )
            date_input, date_picker = create_date_range_picker(set_custom_radio)

        # Right side: Edit Order button
        with ui.row().classes("items-center gap-2"):
            ui.icon("info").classes("text-blue-400").tooltip(
                "Edit mode allows you to reorder customers and projects using arrow buttons"
            )
            edit_button = ui.button(
                "Edit Order", icon="edit", on_click=toggle_edit_mode
            ).props("outline")

    # Bottom row: Display toggle (show bonus instead of time)
    with ui.row().classes("w-full items-center gap-3 mt-2"):
        ui.label("Show Bonus").classes("text-sm")
        show_bonus_toggle = ui.switch(value=False, on_change=on_radio_type_change)
        ui.label("(SEK instead of hours)").classes("text-xs text-gray-400")

    ui.separator().classes(UI_STYLES.get_layout_classes("margin_y_2"))

    # Wire up event handlers
    date_input.value = helpers.get_range_for(selected_time.value)
    selected_time.on("update:model-value", on_radio_time_change)
    # radio_display_selection.on("update:model-value", on_radio_type_change)

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
            try:
                await QE.function_db("insert_time_row", customer_id_int, project_id_int)
            except Exception as e:
                LOG = GlobalRegistry.get("LOG")
                if LOG:
                    LOG.error(f"Error starting timer: {e}")

            # Fetch fresh callback from registry in case it wasn't set earlier
            update_cb = GlobalRegistry.get("update_tab_indicator_now")
            if update_cb:
                try:
                    await update_cb()
                except Exception as e:
                    LOG = GlobalRegistry.get("LOG")
                    if LOG:
                        LOG.error(f"Error calling update_tab_indicator_now: {e}")
            return

        # Unchecked - show dialog for saving comment/DevOps
        checkbox = event.sender

        async def handle_save(git_id_val, comment, store_to_devops):
            """Save time entry with comment and optionally to DevOps."""
            try:
                await QE.function_db(
                    "insert_time_row",
                    customer_id_int,
                    project_id_int,
                    git_id=git_id_val,
                    comment=comment,
                )
            except Exception as e:
                LOG = GlobalRegistry.get("LOG")
                if LOG:
                    LOG.error(f"Error saving timer: {e}")

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

            # call the latest callback from registry
            update_cb2 = GlobalRegistry.get("update_tab_indicator_now")
            if update_cb2:
                try:
                    await update_cb2()
                except Exception as e:
                    LOG = GlobalRegistry.get("LOG")
                    if LOG:
                        LOG.error(
                            f"Error calling update_tab_indicator_now after save: {e}",
                        )

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
        is_time = not show_bonus_toggle.value  # Inverted: toggle ON = show bonus
        column_name = get_column_name(is_time)

        def get_total_string(customer_id):
            """Get formatted total for a customer."""
            total = df[df["customer_id"] == customer_id][column_name].sum()
            return format_value(total, is_time)

        async def make_project_row(
            project, customer_id, project_index=None, total_projects=None
        ):
            """Create a single project row with checkbox/arrows and value."""
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
                # Show arrows in edit mode, checkbox in normal mode
                if edit_mode["enabled"]:

                    def move_project_up():
                        if project_index > 0:
                            projects = project_orders[customer_id]
                            projects[project_index], projects[project_index - 1] = (
                                projects[project_index - 1],
                                projects[project_index],
                            )
                            asyncio.create_task(render_ui())

                    def move_project_down():
                        if project_index < total_projects - 1:
                            projects = project_orders[customer_id]
                            projects[project_index], projects[project_index + 1] = (
                                projects[project_index + 1],
                                projects[project_index],
                            )
                            asyncio.create_task(render_ui())

                    with ui.row().classes("gap-0"):
                        ui.button(icon="arrow_upward", on_click=move_project_up).props(
                            "flat dense size=sm"
                        ).classes("text-blue-400").bind_enabled_from(
                            edit_mode, "enabled", lambda x: x and project_index > 0
                        )
                        ui.button(
                            icon="arrow_downward", on_click=move_project_down
                        ).props("flat dense size=sm").classes(
                            "text-blue-400"
                        ).bind_enabled_from(
                            edit_mode,
                            "enabled",
                            lambda x: x and project_index < total_projects - 1,
                        )
                else:
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

        async def make_customer_card(
            customer_id, customer_name, group, customer_index=None, total_customers=None
        ):
            """Create a customer card with all its projects."""
            with (
                ui.card()
                .classes(UI_STYLES.get_card_classes("xs", "card_padded"))
                .style(
                    "display:flex; flex-direction:column; height:calc(100vh - 300px); box-sizing:border-box;"
                )
            ):
                # Column must be able to shrink properly when content overflows
                with (
                    ui.column()
                    .classes(
                        f"{UI_STYLES.get_layout_classes('time_tracking_customer_column')} flex-1 min-h-0 overflow-hidden"
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
                        # Show customer reorder arrows in edit mode
                        if edit_mode["enabled"]:

                            def move_customer_up():
                                if customer_index > 0:
                                    (
                                        customer_order[customer_index],
                                        customer_order[customer_index - 1],
                                    ) = (
                                        customer_order[customer_index - 1],
                                        customer_order[customer_index],
                                    )
                                    asyncio.create_task(render_ui())

                            def move_customer_down():
                                if customer_index < total_customers - 1:
                                    (
                                        customer_order[customer_index],
                                        customer_order[customer_index + 1],
                                    ) = (
                                        customer_order[customer_index + 1],
                                        customer_order[customer_index],
                                    )
                                    asyncio.create_task(render_ui())

                            with ui.row().classes("gap-1 mr-2"):
                                ui.button(
                                    icon="arrow_upward", on_click=move_customer_up
                                ).props("flat dense size=sm").classes(
                                    "text-green-400"
                                ).bind_enabled_from(
                                    edit_mode,
                                    "enabled",
                                    lambda x: x and customer_index > 0,
                                )
                                ui.button(
                                    icon="arrow_downward", on_click=move_customer_down
                                ).props("flat dense size=sm").classes(
                                    "text-green-400"
                                ).bind_enabled_from(
                                    edit_mode,
                                    "enabled",
                                    lambda x: x
                                    and customer_index < total_customers - 1,
                                )

                        ui.label(str(customer_name)).classes(
                            UI_STYLES.get_widget_style("time_tracking_customer_name")[
                                "classes"
                            ]
                        ).style("grid-column: 1 / span 2; text-align: left;")

                        # Total on the right column, use same classes as project values
                        label_total = (
                            ui.label(total_string)
                            .classes(
                                UI_STYLES.get_widget_style(
                                    "time_tracking_customer_total"
                                )["classes"]
                            )
                            .style(
                                UI_STYLES.get_widget_style(
                                    "time_tracking_customer_total"
                                ).get("style", "")
                            )
                        )
                        customer_total_labels.append((label_total, customer_id))

                    # Visual separator between header and project list
                    ui.separator().classes("w-full border-b border-gray-700 my-2")

                    # Get ordered projects for this customer from database sort_order
                    if customer_id not in project_orders:
                        # Sort by project_sort_order from the database
                        customer_projects = group.sort_values("project_sort_order")
                        project_orders[customer_id] = [
                            (row["project_id"], row["project_name"])
                            for _, row in customer_projects.iterrows()
                        ]

                    with (
                        ui.element()
                        .classes("w-full overflow-auto flex-1 min-h-0")
                        .style("padding-right: 1rem; scrollbar-gutter: stable;")
                    ):
                        # Render projects in the saved order
                        ordered_projects = project_orders[customer_id]
                        total_projects = len(ordered_projects)
                        for proj_idx, (proj_id, proj_name) in enumerate(
                            ordered_projects
                        ):
                            # Find the matching row from the dataframe
                            project_row = group[group["project_id"] == proj_id].iloc[0]
                            await make_project_row(
                                project_row,
                                customer_id,
                                project_index=proj_idx,
                                total_projects=total_projects,
                            )

        customers_from_db = df[
            ["customer_id", "customer_name", "customer_sort_order"]
        ].drop_duplicates()
        customers_from_db = customers_from_db.sort_values("customer_sort_order")

        customers_dict = {
            cust_id: (cust_id, cust_name)
            for cust_id, cust_name in zip(
                customers_from_db["customer_id"], customers_from_db["customer_name"]
            )
        }

        # Only reinitialize if we have new/different customers
        if not customer_order or set(c[0] for c in customer_order) != set(
            customers_dict.keys()
        ):
            customer_order.clear()
            customer_order.extend(customers_dict.values())

        with container:
            with (
                ui.row()
                .classes(UI_STYLES.get_layout_classes("time_tracking_container"))
                .style(UI_STYLES.get_inline_style("time_tracking", "container"))
            ):
                # Render customers in the saved order
                total_customers = len(customer_order)
                for cust_idx, (customer_id, customer_name) in enumerate(customer_order):
                    # Find the matching group from the dataframe
                    group = df[df["customer_id"] == customer_id]
                    if not group.empty:
                        await make_customer_card(
                            customer_id,
                            customer_name,
                            group,
                            customer_index=cust_idx,
                            total_customers=total_customers,
                        )

    async def update_ui():
        """Update the UI labels for project and customer totals based on the latest data."""
        if selected_time.value != "Custom":
            expected_range = helpers.get_range_for(selected_time.value)
            if date_input.value != expected_range:
                date_input.value = expected_range

        df = await get_ui_data()
        is_time = not show_bonus_toggle.value  # Inverted: toggle ON = show bonus
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
