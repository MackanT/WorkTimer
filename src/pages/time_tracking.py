"""
Time Tracking Page

Full time tracking interface with customer/project cards, timers, and DevOps integration.
- Uses event-driven state updates instead of direct UI mutations
- State stored in PageState dataclass, UI renders from state
- Timer changes emit events that trigger state updates
- Granular updates where possible (update_time_tracker) vs full rebuilds (render_time_tracker)
"""

from nicegui import ui
import asyncio
from datetime import datetime, timedelta
from typing import Callable, Dict, Optional, Tuple
from dataclasses import dataclass, field

from ..core import AppCore
from ..helpers import UI_STYLES, extract_devops_id
from .. import helpers

from ..ui.keyboard_handlers import setup_debug_keyboard_handlers

# ============================================================================
# Constants
# ============================================================================

TIME_OPTIONS = ["Day", "Week", "Month", "Year", "All-Time", "Custom"]

# ============================================================================
# State Management
# ============================================================================


@dataclass
class PageState:
    """
    Centralized state for time tracking page.

    UI renders from this state. Updates trigger via events.
    """

    # Display settings
    selected_time: str = "Day"
    date_range: str = ""
    show_bonus: bool = False
    edit_mode_enabled: bool = False

    # Sort orders
    customer_order: list = field(default_factory=list)
    project_orders: Dict[int, list] = field(default_factory=dict)

    # Data cache (keyed by customer_id and (customer_id, project_id))
    customer_totals: Dict[int, float] = field(default_factory=dict)
    project_values: Dict[Tuple[int, int], float] = field(default_factory=dict)

    # UI data (full dataframe cache)
    ui_data_df = None

    def get_project_value(
        self, customer_id: int, project_id: int, column_name: str
    ) -> float:
        """Get project value from dataframe."""
        if self.ui_data_df is None:
            return 0.0
        row = self.ui_data_df[
            (self.ui_data_df["customer_id"] == customer_id)
            & (self.ui_data_df["project_id"] == project_id)
        ]
        if row.empty:
            return 0.0
        return float(row.iloc[0][column_name])

    def get_customer_total(self, customer_id: int, column_name: str) -> float:
        """Get customer total from dataframe."""
        if self.ui_data_df is None:
            return 0.0
        return float(
            self.ui_data_df[self.ui_data_df["customer_id"] == customer_id][
                column_name
            ].sum()
        )

    def update_data(self, df):
        """Update data cache from new dataframe."""
        self.ui_data_df = df


# ============================================================================
# Helper Functions
# ============================================================================


def format_value(value: float, is_time: bool) -> str:
    """Format a value as time (hours) or bonus (SEK)."""
    return f"{value:.2f} h" if is_time else f"{value:,.0f} SEK"


def get_column_name(is_time: bool) -> str:
    """Get the appropriate column name based on display mode."""
    return "total_time" if is_time else "user_bonus"


def create_date_range_picker(on_change_callback) -> tuple:
    """Create date range input with calendar picker."""
    with ui.input("Date range").classes(
        f"{UI_STYLES.get_widget_width('compact')} ml-4 items-center"
    ) as date_input:
        with ui.menu().props("no-parent-event") as menu:
            date_picker = (
                ui.date()
                .props("range")
                .bind_value(
                    date_input,
                    forward=lambda x: (
                        f"{x['from']} - {x['to']}"
                        if isinstance(x, dict) and x
                        else x
                        if isinstance(x, str)
                        else None
                    ),
                    backward=lambda x: (
                        {
                            "from": x.split(" - ")[0],
                            "to": x.split(" - ")[1],
                        }
                        if " - " in (x or "")
                        else None
                    ),
                )
            )
            with ui.row().classes(UI_STYLES.get_layout_classes("row_end")):
                ui.button("Close", on_click=menu.close).props("flat")
        with date_input.add_slot("append"):
            ui.icon("edit_calendar").on("click", menu.open).classes(
                "cursor-pointer items-center"
            )

    date_input.on("update:model-value", on_change_callback)
    date_picker.on("update:model-value", on_change_callback)

    return date_input, date_picker


# ============================================================================
# Main UI
# ============================================================================


@ui.page("/")
async def time_tracking_page():
    """
    Main time tracking page

    Uses per-client AppCore for isolation while maintaining the original
    customer/project card interface with timers and DevOps integration.
    uses PageState for all data, events for updates.
    """

    core = await AppCore.get_or_initialize()
    setup_debug_keyboard_handlers(core)

    # ========================================================================
    # Page State - ALL data stored here, UI renders from this
    # ========================================================================
    state = PageState()

    ignore_next_checkbox_event = False

    # ========================================================================
    # Event Handlers - State Updates
    # ========================================================================

    async def on_timer_started(customer_id: int, project_id: int):
        """Handle timer start event - update UI data."""
        core.event_bus.emit(
            "time_entry_started", customer_id=customer_id, project_id=project_id
        )
        await update_tab_indicator_now()

    async def on_timer_stopped(customer_id: int, project_id: int):
        """Handle timer stop event - refresh data."""
        core.event_bus.emit(
            "time_entry_stopped", customer_id=customer_id, project_id=project_id
        )
        # Update values incrementally without full rebuild
        await update_time_tracker()
        await update_tab_indicator_now()

    # ========================================================================
    # Background Timers
    # ========================================================================

    async def value_refresh_timer():
        """Background timer - refreshes values every minute."""
        try:
            while True:
                await asyncio.sleep(60)
                await update_time_tracker()
                core.logger.debug("Background: Values refreshed (1-minute timer)")
        except asyncio.CancelledError:
            core.logger.debug("Value refresh timer cancelled (client disconnected)")
            return
        except Exception as e:
            core.logger.error(f"Error in value refresh timer: {e}")

    async def midnight_refresh_timer():
        """Background timer - triggers full refresh at midnight for 'Day' view."""
        try:
            while True:
                now = datetime.now()
                tomorrow = (now + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                seconds_until_midnight = (tomorrow - now).total_seconds()
                await asyncio.sleep(seconds_until_midnight)

                # If still on "Day" view at midnight, refresh to show new day
                if state.selected_time == "Day":
                    core.logger.info("Midnight refresh: Updating Day view for new date")
                    date_input.value = helpers.get_range_for("Day")
                    state.date_range = date_input.value
                    await render_time_tracker()
                    core.event_bus.notify("Date changed to new day", type_="info")
                else:
                    core.logger.debug("Midnight: Not on Day view, skipping refresh")
        except asyncio.CancelledError:
            core.logger.debug("Midnight refresh timer cancelled (client disconnected)")
            return
        except Exception as e:
            core.logger.error(f"Error in midnight refresh timer: {e}")

    # ========================================================================
    # Tab Indicator Update Function
    # ========================================================================

    async def update_tab_indicator_now():
        """Update the active timer indicator and emit event."""
        # Check for active timers
        query = "SELECT COUNT(*) as count FROM time WHERE end_time IS NULL"
        result = await core.query_engine.query_db(query)
        active_count = result.iloc[0]["count"] if not result.empty else 0
        ## TODO check this is working

        core.event_bus.emit("active_timer_count_changed", count=active_count)
        return active_count

    # ========================================================================
    # UI Control Handlers
    # ========================================================================

    def set_custom_radio(e):
        """Set time span to Custom when date picker changes."""
        selected_time.value = "Custom"
        state.selected_time = "Custom"
        asyncio.create_task(update_time_tracker())

    def on_radio_time_change(e):
        """Update date range when time span radio changes."""
        state.selected_time = selected_time.value
        date_input.value = helpers.get_range_for(state.selected_time)
        state.date_range = date_input.value
        asyncio.create_task(update_time_tracker())
        core.logger.info(f"Time span changed to: {state.selected_time}")

    def on_radio_type_change(e):
        """Refresh UI when display type changes (Time/Bonus)."""
        state.show_bonus = show_bonus_toggle.value
        asyncio.create_task(update_time_tracker())

    async def toggle_edit_mode():
        """Toggle between normal and edit mode for sorting."""
        state.edit_mode_enabled = not state.edit_mode_enabled

        if state.edit_mode_enabled:
            core.event_bus.notify("Edit mode: Use ↑↓ arrows to reorder", type_="info")
            await render_time_tracker()
            edit_button.set_text("Save Order")
            edit_button.props("color=primary")
        else:
            # Save sort order to database
            try:
                await core.query_engine.function_db(
                    "save_sort_order", state.customer_order, state.project_orders
                )
                core.event_bus.notify(
                    "Sort order saved successfully!", type_="positive"
                )
            except Exception as e:
                core.logger.error(f"Error saving sort order: {e}")
                core.event_bus.notify("Error saving sort order", type_="negative")
            # Rebuild to show checkboxes
            await render_time_tracker()
            edit_button.set_text("Edit Order")
            edit_button.props("color=default")

    # ========================================================================
    # Toolbar Controls
    # ========================================================================

    def render_controls():
        """Render control panel - stable across data refreshes."""
        with ui.row().classes(
            f"w-full items-center gap-6 px-6 py-3 bg-{core.theme.get('toolbar_bg')} rounded-lg"
        ):
            # Group 1: Time span
            with ui.element("div").classes("flex items-center gap-2"):
                ui.label("Time Span").classes(
                    f"text-xs text-{core.theme.get('accent')} uppercase tracking-wide whitespace-nowrap"
                )
                selected_time = (
                    ui.radio(TIME_OPTIONS, value="Day")
                    .props("inline dense")
                    .classes("items-center")
                )

            ui.element("div").classes(f"h-6 w-px bg-{core.theme.get('divider')}")

            # Group 2: Date range
            with ui.element("div").classes("flex items-center gap-2"):
                ui.label("Range").classes(
                    f"text-xs text-{core.theme.get('accent')} uppercase tracking-wide whitespace-nowrap"
                )
                date_input, date_picker = create_date_range_picker(set_custom_radio)

            ui.element("div").classes(f"h-6 w-px bg-{core.theme.get('divider')}")

            # Group 3: Show Bonus toggle
            with ui.element("div").classes("flex items-center gap-2"):
                ui.label("Bonus").classes(
                    f"text-xs text-{core.theme.get('accent')} uppercase tracking-wide whitespace-nowrap"
                )
                show_bonus_toggle = ui.switch(
                    value=False, on_change=on_radio_type_change
                )

            ui.space()

            # Group 4: Edit button
            edit_button = (
                ui.button("Edit Order", icon="edit", on_click=toggle_edit_mode)
                .props("outline")
                .classes("whitespace-nowrap")
                .tooltip(
                    "Edit mode allows you to reorder customers and projects using arrow buttons"
                )
            )

        return selected_time, date_input, date_picker, show_bonus_toggle, edit_button

    # Render controls once
    selected_time, date_input, date_picker, show_bonus_toggle, edit_button = (
        render_controls()
    )

    # ========================================================================
    # Checkbox Event Handling
    # ========================================================================

    def _create_action_buttons(on_save, on_delete, on_close):
        """Create standard Save/Delete/Close button row for dialogs."""
        with ui.row().classes("justify-end gap-2"):
            btn_classes = UI_STYLES.get_widget_width("button")
            ui.button("Save", on_click=on_save).classes(btn_classes)
            ui.button("Delete", on_click=on_delete).props("color=negative").classes(
                f"q-btn--warning {btn_classes}"
            )
            ui.button("Close", on_click=on_close).props("flat").classes(btn_classes)

    async def show_time_entry_dialog(
        customer_id: int,
        project_id: int,
        query_engine,
        devops_engine,
        logger,
        on_save_callback: Optional[Callable] = None,
        on_delete_callback: Optional[Callable] = None,
        on_close_callback: Optional[Callable] = None,
    ) -> None:
        """
        Show dialog for completing a time entry with comment and DevOps integration.

        Args:
            customer_id: Customer ID for the time entry
            project_id: Project ID for the time entry
            query_engine: Query engine instance
            devops_engine: DevOps engine instance
            logger: Logger instance
            on_save_callback: Async function to call on save with (git_id, comment, store_to_devops)
            on_delete_callback: Async function to call on delete
            on_close_callback: Function to call on close/cancel
        """
        QE = query_engine
        DO = devops_engine
        LOG = logger

        # Query project/customer info
        df = await QE.query_db(
            f"""
            select distinct t.customer_name, t.project_name, p.git_id 
            from time t
            left join projects p on p.project_id = t.project_id
            where t.customer_id = {customer_id} and t.project_id = {project_id}
            """
        )

        # Extract values with defaults
        c_name = df.iloc[0]["customer_name"] if not df.empty else "Unknown"
        p_name = df.iloc[0]["project_name"] if not df.empty else "Unknown"
        git_id = df.iloc[0]["git_id"] if not df.empty else 0
        has_git_id = git_id is not None and git_id > 0

        # Check DevOps connection using engine method
        has_devops = DO.has_customer_connection(c_name) if DO else False

        with ui.dialog().props("persistent") as popup:
            with ui.card().classes(UI_STYLES.get_widget_width("extra_wide")):
                # Title
                ui.label(f"{p_name} - {c_name}").classes("text-h6 w-full")

                # DevOps ID selector (if available)
                id_input = None
                id_checkbox = None
                if has_devops:
                    id_options = DO.df[
                        (DO.df["customer_name"] == c_name)
                        & (DO.df["state"].isin(["Active", "New"]))
                    ][["display_name", "id"]].dropna()
                    id_input = ui.select(
                        id_options["display_name"].tolist(),
                        with_input=True,
                        label="DevOps-ID",
                    ).classes("w-full -mb-2")

                    if has_git_id:
                        match = id_options[id_options["id"] == git_id]
                        id_input.value = (
                            match["display_name"].iloc[0] if not match.empty else None
                        )

                    with ui.row().classes("w-full items-center justify-between -mt-2"):

                        def toggle_switch():
                            id_checkbox.value = not id_checkbox.value
                            id_checkbox.update()

                        ui.label("Store to DevOps").on("click", toggle_switch).classes(
                            "cursor-pointer"
                        )
                        id_checkbox = ui.switch(value=has_git_id).props("dense")

                # Comment input
                comment_input = ui.textarea(
                    label="Comment", placeholder="What work was done?"
                ).classes("w-full -mt-2")

                # Action buttons
                async def handle_save():
                    """Save time entry with parsed DevOps ID."""
                    git_id_val = None
                    store_to_devops = False

                    if has_devops and id_input is not None:
                        git_id_val = extract_devops_id(id_input.value)
                        store_to_devops = id_checkbox.value if id_checkbox else False

                    if LOG:
                        LOG.debug(
                            f"Time entry save: git_id={git_id_val}, devops={store_to_devops}, "
                            f"customer={customer_id}, project={project_id}",
                        )

                    if on_save_callback:
                        await on_save_callback(
                            git_id_val, comment_input.value, store_to_devops
                        )

                    popup.close()

                async def handle_delete():
                    """Delete the time entry."""
                    if on_delete_callback:
                        await on_delete_callback()
                    ui.notify("Entry deleted", color="negative")
                    popup.close()

                def handle_close():
                    """Close dialog without saving."""
                    if on_close_callback:
                        on_close_callback()
                    popup.close()

                # Button row
                _create_action_buttons(handle_save, handle_delete, handle_close)

        popup.open()

    async def on_checkbox_change(event, checked, customer_id, project_id):
        """Handle checkbox change for time/project row."""
        nonlocal ignore_next_checkbox_event
        if ignore_next_checkbox_event:
            ignore_next_checkbox_event = False
            return

        customer_id_int = int(customer_id)
        project_id_int = int(project_id)

        if checked:
            try:
                await core.query_engine.function_db(
                    "insert_time_row", customer_id_int, project_id_int
                )
                await on_timer_started(customer_id_int, project_id_int)
            except Exception as e:
                core.logger.error(f"Error starting timer: {e}")
                core.event_bus.notify(f"Error starting timer: {e}", type_="negative")
            return

        # Unchecked - show dialog for saving comment/DevOps
        checkbox = event.sender

        async def handle_save(git_id_val, comment, store_to_devops):
            """Save time entry with comment and optionally to DevOps."""
            try:
                await core.query_engine.function_db(
                    "insert_time_row",
                    customer_id_int,
                    project_id_int,
                    git_id=git_id_val,
                    comment=comment,
                )
                await on_timer_stopped(customer_id_int, project_id_int)

                core.event_bus.notify("Entry saved successfully!", type_="positive")

            except Exception as e:
                core.logger.error(f"Error saving timer: {e}")
                core.event_bus.notify(f"Error saving timer: {e}", type_="negative")
                return

            # Save to DevOps if requested
            if store_to_devops and git_id_val and git_id_val > 0:
                customer_name_df = await core.query_engine.query_db(
                    "select customer_name from customers where customer_id = ?",
                    params=(customer_id_int,),
                )
                if (
                    core.devops_engine
                    and core.devops_engine.manager
                    and not customer_name_df.empty
                ):
                    status, msg = core.devops_engine.manager.save_comment(
                        customer_name=customer_name_df.iloc[0]["customer_name"],
                        comment=comment,
                        git_id=git_id_val,
                    )
                    col = "positive" if status else "negative"
                    core.event_bus.notify(msg, type_=col)

        async def handle_delete():
            """Delete the time entry."""
            await core.query_engine.function_db(
                "delete_time_row", customer_id_int, project_id_int
            )
            await on_timer_stopped(customer_id_int, project_id_int)

        def handle_close():
            """Close dialog without saving - reset checkbox."""
            nonlocal ignore_next_checkbox_event
            ignore_next_checkbox_event = True
            checkbox.set_value(True)

        await show_time_entry_dialog(
            customer_id=customer_id_int,
            project_id=project_id_int,
            query_engine=core.query_engine,
            devops_engine=core.devops_engine,
            logger=core.logger,
            on_save_callback=handle_save,
            on_delete_callback=handle_delete,
            on_close_callback=handle_close,
        )

    def make_callback(customer_id, project_id):
        return lambda e: on_checkbox_change(e, e.value, customer_id, project_id)

    # ========================================================================
    # Data Functions
    # ========================================================================

    async def get_ui_data():
        """Fetch UI data for the selected date range from database."""
        date_range_str = date_input.value
        start_date, end_date = helpers.parse_date_range(date_range_str)

        if not start_date or not end_date:
            today = datetime.now().strftime("%Y%m%d")
            start_date = end_date = today

        return await core.query_engine.function_db(
            "get_customer_ui_list", start_date=start_date, end_date=end_date
        )

    # ========================================================================
    # Render Functions
    # ========================================================================

    # Storage for label widgets for incremental updates
    value_label_refs = {}
    customer_total_label_refs = {}

    async def render_time_tracker():
        """
        Render the main time tracking UI, grouped by customer and project.

        Called only when:
        - Initial page load
        - Edit mode toggle (reorder UI changes)
        - Time range changes (major data change)
        """
        core.logger.debug("Running render_time_tracker (full rebuild)")

        df = await get_ui_data()
        state.update_data(df)
        container.clear()

        # Clear label references for new render
        value_label_refs.clear()
        customer_total_label_refs.clear()

        # Cache display mode
        is_time = not state.show_bonus
        column_name = get_column_name(is_time)

        def get_total_string(customer_id):
            """Get formatted total for a customer from state."""
            total = state.get_customer_total(customer_id, column_name)
            return format_value(total, is_time)

        async def make_project_row(
            project, customer_id, project_index=None, total_projects=None
        ):
            """Create a single project row with checkbox/arrows and value."""
            sql_query = (
                f"select * from time where customer_id = {customer_id} "
                f"and project_id = {project['project_id']} and end_time is null"
            )
            df_counts = await core.query_engine.query_db(sql_query)
            initial_state_val = bool(len(df_counts) > 0)

            with (
                ui.row()
                .classes(
                    UI_STYLES.get_layout_classes("time_tracking_project_row")
                    + " items-center"
                )
                .style(
                    (UI_STYLES.get_inline_style("time_tracking", "project_row") or "")
                    + " display: grid; grid-template-columns: auto 1fr auto; gap: 0.5rem; width: 100%;"
                )
            ):
                # Show arrows in edit mode, checkbox in normal mode
                if state.edit_mode_enabled:

                    def move_project_up():
                        if project_index > 0:
                            projects = state.project_orders[customer_id]
                            projects[project_index], projects[project_index - 1] = (
                                projects[project_index - 1],
                                projects[project_index],
                            )
                            asyncio.create_task(render_time_tracker())

                    def move_project_down():
                        if project_index < total_projects - 1:
                            projects = state.project_orders[customer_id]
                            projects[project_index], projects[project_index + 1] = (
                                projects[project_index + 1],
                                projects[project_index],
                            )
                            asyncio.create_task(render_time_tracker())

                    with ui.row().classes("gap-0"):
                        ui.button(icon="arrow_upward", on_click=move_project_up).props(
                            "flat dense size=sm"
                        ).classes(f"text-{core.theme.get('accent')}").bind_enabled_from(
                            state,
                            "edit_mode_enabled",
                            lambda x: x and project_index > 0,
                        )
                        ui.button(
                            icon="arrow_downward", on_click=move_project_down
                        ).props("flat dense size=sm").classes(
                            f"text-{core.theme.get('accent')}"
                        ).bind_enabled_from(
                            state,
                            "edit_mode_enabled",
                            lambda x: x and project_index < total_projects - 1,
                        )
                else:
                    ui.checkbox(
                        on_change=make_callback(
                            project["customer_id"], project["project_id"]
                        ),
                        value=initial_state_val,
                    )

                ui.label(str(project["project_name"])).classes(
                    UI_STYLES.get_widget_style("time_tracking_project_name")["classes"]
                ).style(
                    "overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"
                )

                value = project[column_name]
                total_string = format_value(value, is_time)

                project_value_style = UI_STYLES.get_widget_style(
                    "time_tracking_project_value"
                )
                value_label = (
                    ui.label(f"{total_string}")
                    .classes(project_value_style["classes"])
                    .style(
                        project_value_style.get("style", "") + " white-space: nowrap;"
                    )
                )
                value_label_refs[(customer_id, project["project_id"])] = value_label

        async def make_customer_card(
            customer_id, customer_name, group, customer_index=None, total_customers=None
        ):
            """Create a customer card with all its projects."""
            with (
                ui.card()
                .classes(UI_STYLES.get_card_classes("xs", "card_padded"))
                .style(
                    "display:flex; flex-direction:column; height:calc(100vh - 220px); min-width:280px; box-sizing:border-box;"
                )
                .props("flat")
            ):
                with (
                    ui.column()
                    .classes(
                        f"{UI_STYLES.get_layout_classes('time_tracking_customer_column')} flex-1 min-h-0"
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
                        # Left side: arrows (if edit mode) + customer name
                        with ui.element().style(
                            "display: flex; align-items: center; gap: 0.25rem; overflow: hidden;"
                        ):
                            # Show customer reorder arrows in edit mode
                            if state.edit_mode_enabled:

                                def move_customer_up():
                                    if customer_index > 0:
                                        (
                                            state.customer_order[customer_index],
                                            state.customer_order[customer_index - 1],
                                        ) = (
                                            state.customer_order[customer_index - 1],
                                            state.customer_order[customer_index],
                                        )
                                        asyncio.create_task(render_time_tracker())

                                def move_customer_down():
                                    if customer_index < total_customers - 1:
                                        (
                                            state.customer_order[customer_index],
                                            state.customer_order[customer_index + 1],
                                        ) = (
                                            state.customer_order[customer_index + 1],
                                            state.customer_order[customer_index],
                                        )
                                        asyncio.create_task(render_time_tracker())

                                with ui.row().classes("gap-0"):
                                    ui.button(
                                        icon="arrow_back",
                                        on_click=move_customer_up,
                                    ).props("flat dense size=sm").classes(
                                        f"text-{core.theme.get('accent')}"
                                    ).bind_enabled_from(
                                        state,
                                        "edit_mode_enabled",
                                        lambda x: x and customer_index > 0,
                                    )
                                    ui.button(
                                        icon="arrow_forward",
                                        on_click=move_customer_down,
                                    ).props("flat dense size=sm").classes(
                                        f"text-{core.theme.get('accent')}"
                                    ).bind_enabled_from(
                                        state,
                                        "edit_mode_enabled",
                                        lambda x: (
                                            x and customer_index < total_customers - 1
                                        ),
                                    )

                            ui.label(str(customer_name)).classes(
                                UI_STYLES.get_widget_style(
                                    "time_tracking_customer_name"
                                )["classes"]
                            ).style(
                                "overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left;"
                            )

                        customer_total_label = (
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
                                + " white-space: nowrap;"
                            )
                        )
                        customer_total_label_refs[customer_id] = customer_total_label

                    ui.separator().classes(
                        f"w-full border-b border-{core.theme.get('divider')} my-2"
                    )

                    # Get ordered projects for this customer
                    customer_projects = group.sort_values("project_sort_order")
                    db_ordered = [
                        (row["project_id"], row["project_name"])
                        for _, row in customer_projects.iterrows()
                    ]

                    if customer_id not in state.project_orders:
                        state.project_orders[customer_id] = db_ordered
                    else:
                        # Merge DB changes
                        existing = state.project_orders[customer_id]
                        existing_ids = [p[0] for p in existing]
                        for pid, pname in db_ordered:
                            if pid not in existing_ids:
                                existing.append((pid, pname))
                        db_ids = [p[0] for p in db_ordered]
                        state.project_orders[customer_id] = [
                            p for p in existing if p[0] in db_ids
                        ]

                    with (
                        ui.element()
                        .classes("w-full overflow-auto flex-1 min-h-0")
                        .style("padding-right: 1rem; scrollbar-gutter: stable;")
                    ):
                        ordered_projects = state.project_orders[customer_id]
                        total_projects = len(ordered_projects)
                        for proj_idx, (proj_id, proj_name) in enumerate(
                            ordered_projects
                        ):
                            project_row = group[group["project_id"] == proj_id].iloc[0]
                            await make_project_row(
                                project_row,
                                customer_id,
                                project_index=proj_idx,
                                total_projects=total_projects,
                            )

        # Get customers from database
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

        # Initialize customer order if needed
        if not state.customer_order or set(c[0] for c in state.customer_order) != set(
            customers_dict.keys()
        ):
            state.customer_order.clear()
            state.customer_order.extend(customers_dict.values())

        # Clear and rebuild container
        container.clear()
        with container:
            with ui.row(wrap=False):
                total_customers = len(state.customer_order)
                for cust_idx, (customer_id, customer_name) in enumerate(
                    state.customer_order
                ):
                    group = df[df["customer_id"] == customer_id]
                    if not group.empty:
                        await make_customer_card(
                            customer_id,
                            customer_name,
                            group,
                            customer_index=cust_idx,
                            total_customers=total_customers,
                        )

        core.logger.debug("Completed render_time_tracker (full rebuild)")

    async def update_time_tracker():
        """
        Update only the displayed values without rebuilding UI structure.

        Much faster than full rebuild - just updates text in existing labels.
        Used when toggling time/bonus or after timer stops.
        """
        df = await get_ui_data()
        state.update_data(df)

        # Determine display mode
        is_time = not state.show_bonus
        column_name = get_column_name(is_time)

        # Update project value labels
        for (cust_id, proj_id), label in value_label_refs.items():
            value = state.get_project_value(cust_id, proj_id, column_name)
            label.set_text(format_value(value, is_time))

        # Update customer total labels
        for cust_id, label in customer_total_label_refs.items():
            total = state.get_customer_total(cust_id, column_name)
            label.set_text(format_value(total, is_time))

        core.logger.debug("Values updated incrementally")

    # ========================================================================
    # Initialize UI Elements
    # ========================================================================

    # Wire up event handlers
    date_input.value = helpers.get_range_for(selected_time.value)
    state.date_range = date_input.value
    selected_time.on("update:model-value", on_radio_time_change)

    ui.query("html").style("overflow: hidden;")
    ui.query("body").style("overflow: hidden;")

    ## DEBUG: Uncomment to add red outline to all elements for layout debugging
    # ui.add_css("""
    #     * { outline: 1px solid red; }
    # """)

    container = ui.scroll_area().classes("w-full").style("height: calc(100vh - 150px)")
    core._setup_page_timers(
        "time_tracking", value_refresh_timer, midnight_refresh_timer
    )

    await render_time_tracker()
