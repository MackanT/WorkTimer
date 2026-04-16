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
from typing import Callable, Dict, Optional
from dataclasses import dataclass, field

from ..core import AppCore
from ..helpers import UI_STYLES, extract_devops_id
from .. import helpers

from ..ui.elements import (
    toolbar,
    toolbar_group,
    entity_card_shell,
    entity_card_header,
    entity_card_content,
)

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
    show_bonus: bool = False
    edit_mode_enabled: bool = False

    # Sort orders
    customer_order: list = field(default_factory=list)
    project_orders: Dict[int, list] = field(default_factory=dict)

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


async def time_tracking_page():
    """
    Main time tracking page

    Uses per-client AppCore for isolation while maintaining the original
    customer/project card interface with timers and DevOps integration.
    uses PageState for all data, events for updates.

    Note: No @ui.page decorator - accessed via SPA sub_pages in root.py
    Direct access to /time is handled by redirect in root.py
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
                if not core._client_alive:
                    return
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

                if not core._client_alive:
                    return

                # If still on "Day" view at midnight, refresh to show new day
                if state.selected_time == "Day":
                    core.logger.info("Midnight refresh: Updating Day view for new date")
                    date_input.value = helpers.get_range_for("Day")
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
        """Update the active timer indicator, emit event with names for nav bar."""
        result = await core.query_engine.query_db(
            """
            SELECT c.customer_name, p.project_name
            FROM time t
            JOIN customers c ON t.customer_id = c.customer_id
            JOIN projects p ON t.project_id = p.project_id
            WHERE t.end_time IS NULL
            ORDER BY c.customer_name, p.project_name
            """
        )
        active_names = [
            f"{r['customer_name']} / {r['project_name']}"
            for _, r in result.iterrows()
        ] if not result.empty else []

        core.event_bus.emit(
            "active_timer_count_changed",
            count=len(active_names),
            names=active_names,
        )

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

    def render_toolbar():
        """Render control panel - stable across data refreshes."""
        with toolbar(core.theme):
            with toolbar_group(core.theme, "Time Span", divider_after=True):
                selected_time = (
                    ui.radio(TIME_OPTIONS, value="Day")
                    .props("inline dense")
                    .classes("items-center")
                )
            with toolbar_group(core.theme, "Range", divider_after=True):
                date_input, date_picker = create_date_range_picker(set_custom_radio)
            with toolbar_group(core.theme, "Bonus", divider_after=True):
                show_bonus_toggle = ui.switch(
                    value=False, on_change=on_radio_type_change
                )
            ui.space()
            edit_button = (
                ui.button("Edit Order", icon="edit", on_click=toggle_edit_mode)
                .props("outline")
                .classes("whitespace-nowrap shrink-0")
                .tooltip(
                    "Edit mode allows you to reorder customers and projects using arrow buttons"
                )
            )

        return selected_time, date_input, date_picker, show_bonus_toggle, edit_button

    selected_time, date_input, date_picker, show_bonus_toggle, edit_button = (
        render_toolbar()
    )

    # ========================================================================
    # Checkbox Event Handling
    # ========================================================================

    def _create_action_buttons(on_save, on_close, on_delete=None, save_label="Save"):
        """Create standard action button row for dialogs. Delete button is optional."""
        with ui.row().classes("justify-end gap-2"):
            btn_classes = UI_STYLES.get_widget_width("button")
            ui.button(save_label, on_click=on_save).classes(btn_classes)
            if on_delete is not None:
                ui.button("Delete", on_click=on_delete).props("color=negative").classes(
                    f"q-btn--warning {btn_classes}"
                )
            ui.button("Close", on_click=on_close).props("flat").classes(btn_classes)

    def _build_devops_selector(devops_engine, c_name, git_id, has_git_id):
        """Render DevOps ID dropdown + 'Store to DevOps' toggle. Returns (id_input, id_checkbox)."""
        id_checkbox = None
        id_options = devops_engine.df[
            (devops_engine.df["customer_name"] == c_name)
            & (devops_engine.df["state"].isin(["Active", "New"]))
        ][["display_name", "id"]].dropna()
        id_input = ui.select(
            id_options["display_name"].tolist(),
            with_input=True,
            label="DevOps-ID",
        ).classes("w-full -mb-2")
        if has_git_id:
            match = id_options[id_options["id"] == git_id]
            id_input.value = match["display_name"].iloc[0] if not match.empty else None
        with ui.row().classes("w-full items-center justify-between -mt-2"):
            def toggle_switch():
                id_checkbox.value = not id_checkbox.value
                id_checkbox.update()
            ui.label("Store to DevOps").on("click", toggle_switch).classes("cursor-pointer")
            id_checkbox = ui.switch(value=has_git_id).props("dense")
        return id_input, id_checkbox

    async def show_time_entry_dialog(
        customer_id: int,
        project_id: int,
        on_save_callback: Optional[Callable] = None,
        on_delete_callback: Optional[Callable] = None,
        on_close_callback: Optional[Callable] = None,
    ) -> None:
        """Show dialog for completing a time entry with comment and DevOps integration."""
        # Query project/customer info
        df = await core.query_engine.query_db(
            """
            select distinct t.customer_name, t.project_name, p.git_id
            from time t
            left join projects p on p.project_id = t.project_id
            where t.customer_id = ? and t.project_id = ?
            """,
            params=(customer_id, project_id),
        )

        # Extract values with defaults
        c_name = df.iloc[0]["customer_name"] if not df.empty else "Unknown"
        p_name = df.iloc[0]["project_name"] if not df.empty else "Unknown"
        git_id = df.iloc[0]["git_id"] if not df.empty else 0
        has_git_id = git_id is not None and git_id > 0

        # Check DevOps connection using engine method
        has_devops = core.devops_engine.has_customer_connection(c_name) if core.devops_engine else False

        with ui.dialog().props("persistent") as popup:
            with ui.card().classes(UI_STYLES.get_widget_width("extra_wide")):
                # Title
                ui.label(f"{p_name} - {c_name}").classes("text-h6 w-full")

                # DevOps ID selector (if available)
                id_input = None
                id_checkbox = None
                if has_devops:
                    id_input, id_checkbox = _build_devops_selector(
                        core.devops_engine, c_name, git_id, has_git_id
                    )

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

                    core.logger.debug(
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
                _create_action_buttons(handle_save, handle_close, on_delete=handle_delete)

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
            on_save_callback=handle_save,
            on_delete_callback=handle_delete,
            on_close_callback=handle_close,
        )

    def make_callback(customer_id, project_id):
        async def _cb(e):
            await on_checkbox_change(e, e.value, customer_id, project_id)
        return _cb

    async def show_manual_time_entry_dialog(customer_id: int, project_id: int):
        """Populate the pre-created dialog shell and open it."""
        df = await core.query_engine.query_db(
            """
            select c.customer_name, p.project_name, p.git_id
            from customers c
            join projects p on p.customer_id = c.customer_id
            where c.customer_id = ? and p.project_id = ?
            """,
            params=(customer_id, project_id),
        )
        c_name = df.iloc[0]["customer_name"] if not df.empty else "Unknown"
        p_name = df.iloc[0]["project_name"] if not df.empty else "Unknown"
        git_id = df.iloc[0]["git_id"] if not df.empty else 0
        has_git_id = git_id is not None and git_id > 0
        has_devops = core.devops_engine.has_customer_connection(c_name) if core.devops_engine else False

        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)
        dt_fmt = "%Y-%m-%dT%H:%M"

        _manual_card.clear()
        with _manual_card:
            ui.label(f"{p_name} - {c_name}").classes("text-h6 w-full")
            ui.label("Add manual time entry").classes(
                f"text-caption text-{core.theme.get('muted')} -mt-2 mb-2"
            )

            with ui.row().classes("w-full gap-3"):
                start_input = (
                    ui.input(label="Start time", value=one_hour_ago.strftime(dt_fmt))
                    .props('type="datetime-local"')
                    .classes("flex-1")
                )
                end_input = (
                    ui.input(label="End time", value=now.strftime(dt_fmt))
                    .props('type="datetime-local"')
                    .classes("flex-1")
                )

            id_input = None
            id_checkbox = None
            git_id_number_input = None
            if has_devops:
                id_input, id_checkbox = _build_devops_selector(
                    core.devops_engine, c_name, git_id, has_git_id
                )
            else:
                git_id_number_input = (
                    ui.number(label="Git ID", value=git_id if has_git_id else None, min=0)
                    .props("dense outlined")
                    .classes("w-full")
                )

            comment_input = ui.textarea(
                label="Comment", placeholder="What work was done?"
            ).classes("w-full -mt-2")

            async def handle_save():
                git_id_val = None
                if has_devops and id_input is not None:
                    git_id_val = extract_devops_id(id_input.value)
                elif git_id_number_input is not None and git_id_number_input.value:
                    git_id_val = int(git_id_number_input.value)
                try:
                    await core.query_engine.function_db(
                        "insert_manual_time_row",
                        customer_id,
                        project_id,
                        start_input.value,
                        end_input.value,
                        git_id=git_id_val,
                        comment=comment_input.value or None,
                    )
                    core.event_bus.notify("Time entry added!", type_="positive")
                    await update_time_tracker()
                except Exception as e:
                    core.logger.error(f"Manual time entry failed: {e}")
                    core.event_bus.notify(f"Error saving entry: {e}", type_="negative")
                _manual_dialog.close()

            def handle_close():
                _manual_dialog.close()

            _create_action_buttons(handle_save, handle_close)

        _manual_dialog.open()

    async def show_manual_start_dialog(customer_id: int, project_id: int):
        """Open a small dialog to start a timer with a custom start time."""
        # Guard: refuse if a timer is already running for this project
        active = await core.query_engine.query_db(
            "select 1 from time where customer_id = ? and project_id = ? and end_time is null limit 1",
            params=(customer_id, project_id),
        )
        if not active.empty:
            core.event_bus.notify(
                "A timer is already running for this project — stop it first",
                type_="warning",
            )
            return

        df = await core.query_engine.query_db(
            "select c.customer_name, p.project_name from customers c "
            "join projects p on p.customer_id = c.customer_id "
            "where c.customer_id = ? and p.project_id = ?",
            params=(customer_id, project_id),
        )
        c_name = df.iloc[0]["customer_name"] if not df.empty else "Unknown"
        p_name = df.iloc[0]["project_name"] if not df.empty else "Unknown"

        now = datetime.now()
        dt_fmt = "%Y-%m-%dT%H:%M"

        _manual_start_card.clear()
        with _manual_start_card:
            ui.label(f"{p_name} - {c_name}").classes("text-h6 w-full")
            ui.label("Start timer from a past time").classes(
                f"text-caption text-{core.theme.get('muted')} -mt-2 mb-2"
            )

            start_input = (
                ui.input(label="Start time", value=now.strftime(dt_fmt))
                .props('type="datetime-local"')
                .classes("w-full")
            )

            async def handle_save():
                try:
                    await core.query_engine.function_db(
                        "insert_timer_start_row",
                        customer_id,
                        project_id,
                        start_input.value,
                    )
                    cb = checkbox_refs.get((customer_id, project_id))
                    if cb:
                        nonlocal ignore_next_checkbox_event
                        ignore_next_checkbox_event = True
                        cb.set_value(True)
                    await on_timer_started(customer_id, project_id)
                    core.event_bus.notify("Timer started!", type_="positive")
                except Exception as e:
                    core.logger.error(f"Manual start failed: {e}")
                    core.event_bus.notify(f"Error starting timer: {e}", type_="negative")
                _manual_start_dialog.close()

            def handle_close():
                _manual_start_dialog.close()

            _create_action_buttons(handle_save, handle_close, save_label="Start")

        _manual_start_dialog.open()

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
    checkbox_refs = {}

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
        state.ui_data_df = df

        # Clear label references for new render
        value_label_refs.clear()
        customer_total_label_refs.clear()
        checkbox_refs.clear()

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
            df_counts = await core.query_engine.query_db(
                "select 1 from time where customer_id = ? and project_id = ? and end_time is null limit 1",
                params=(customer_id, int(project["project_id"])),
            )
            initial_state_val = not df_counts.empty

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
                    cb = ui.checkbox(
                        on_change=make_callback(
                            project["customer_id"], project["project_id"]
                        ),
                        value=initial_state_val,
                    )
                    checkbox_refs[(int(project["customer_id"]), int(project["project_id"]))] = cb

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
                    ui.label(total_string)
                    .classes(project_value_style["classes"])
                    .style(
                        project_value_style.get("style", "") + " white-space: nowrap;"
                    )
                )
                value_label_refs[(customer_id, project["project_id"])] = value_label

                with ui.context_menu():
                    async def _open_manual(cid=int(project["customer_id"]), pid=int(project["project_id"])):
                        await show_manual_time_entry_dialog(cid, pid)
                    async def _open_manual_start(cid=int(project["customer_id"]), pid=int(project["project_id"])):
                        await show_manual_start_dialog(cid, pid)
                    ui.menu_item("Add time entry", on_click=_open_manual).props("icon=add_circle")
                    ui.menu_item("Start from past time", on_click=_open_manual_start).props("icon=history")

        async def make_customer_card(
            customer_id, customer_name, group, customer_index=None, total_customers=None
        ):
            """Create a customer card with all its projects."""
            total_string = get_total_string(customer_id)

            with entity_card_shell():
                with entity_card_header():
                    # Left side: arrows + customer name
                    with ui.element("div").style(
                        "display:flex; align-items:center; gap:0.25rem; overflow:hidden;"
                    ):
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
                            UI_STYLES.get_widget_style("time_tracking_customer_name")[
                                "classes"
                            ]
                        ).style(
                            "overflow:hidden; text-overflow:ellipsis; white-space:nowrap; text-align:left;"
                        )

                    # Right side: total label
                    lbl = (
                        ui.label(total_string)
                        .classes(
                            UI_STYLES.get_widget_style("time_tracking_customer_total")[
                                "classes"
                            ]
                        )
                        .style(
                            UI_STYLES.get_widget_style(
                                "time_tracking_customer_total"
                            ).get("style", "")
                            + " white-space:nowrap;"
                        )
                    )

                ui.separator().classes(
                    UI_STYLES.get_layout_classes("divider_row")
                )

                with entity_card_content():
                    # Merge/init project order
                    customer_projects = group.sort_values("project_sort_order")
                    db_ordered = [
                        (row["project_id"], row["project_name"])
                        for _, row in customer_projects.iterrows()
                    ]

                    if customer_id not in state.project_orders:
                        state.project_orders[customer_id] = db_ordered
                    else:
                        existing = state.project_orders[customer_id]
                        existing_ids = [p[0] for p in existing]
                        for pid, pname in db_ordered:
                            if pid not in existing_ids:
                                existing.append((pid, pname))
                        db_ids = [p[0] for p in db_ordered]
                        state.project_orders[customer_id] = [
                            p for p in existing if p[0] in db_ids
                        ]

                    ordered_projects = state.project_orders[customer_id]
                    total_projects = len(ordered_projects)
                    for proj_idx, (proj_id, proj_name) in enumerate(ordered_projects):
                        project_row = group[group["project_id"] == proj_id].iloc[0]
                        await make_project_row(
                            project_row,
                            customer_id,
                            project_index=proj_idx,
                            total_projects=total_projects,
                        )

            customer_total_label_refs[customer_id] = lbl

        # Get customers from database
        customers_from_db = df[
            ["customer_id", "customer_name", "customer_sort_order"]
        ].drop_duplicates()
        customers_from_db = customers_from_db.sort_values("customer_sort_order")

        customers_list = list(
            zip(customers_from_db["customer_id"], customers_from_db["customer_name"])
        )
        current_ids = {c[0] for c in customers_list}

        # Initialize customer order if needed
        if not state.customer_order or {c[0] for c in state.customer_order} != current_ids:
            state.customer_order.clear()
            state.customer_order.extend(customers_list)

        # Rebuild container
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
        state.ui_data_df = df

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
    selected_time.on("update:model-value", on_radio_time_change)

    ## DEBUG: Uncomment to add red outline to all elements for layout debugging
    # ui.add_css("""
    #     * { outline: 1px solid red; }
    # """)

    container = ui.scroll_area().classes("wt-page-content w-full")

    # Pre-create dialog shell so it exists in the proper slot context at page load.
    # show_manual_time_entry_dialog() clears + rebuilds the card body and then opens it.
    with ui.dialog().props("persistent") as _manual_dialog:
        _manual_card = ui.card().classes(UI_STYLES.get_widget_width("extra_wide"))

    with ui.dialog().props("persistent") as _manual_start_dialog:
        _manual_start_card = ui.card().classes(UI_STYLES.get_widget_width("standard"))

    core._setup_page_timers(
        "time_tracking", value_refresh_timer, midnight_refresh_timer
    )

    await render_time_tracker()
    await update_tab_indicator_now()  # Populate active-timer chips on initial load
