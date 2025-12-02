"""
Reusable dialog components for WorkTimer UI.

Provides standardized dialogs for common operations:
- Time entry completion dialog (with DevOps integration)
- Confirmation dialogs
"""

from typing import Callable, Optional
from nicegui import ui
from ..helpers import UI_STYLES, extract_devops_id, extract_id_from_text
from ..globals import GlobalRegistry


def _create_action_buttons(on_save, on_delete, on_close):
    """Create standard Save/Delete/Close button row for dialogs."""
    with ui.row().classes("justify-end gap-2"):
        btn_classes = UI_STYLES.get_widget_width("button")
        ui.button("Save", on_click=on_save).classes(btn_classes)
        ui.button("Delete", on_click=on_delete).props("color=negative").classes(
            f"q-btn--warning {btn_classes}"
        )
        ui.button("Close", on_click=on_close).props("flat").classes(btn_classes)


# ============================================================================
# Dialog Components
# ============================================================================


async def show_time_entry_dialog(
    customer_id: int,
    project_id: int,
    on_save_callback: Optional[Callable] = None,
    on_delete_callback: Optional[Callable] = None,
    on_close_callback: Optional[Callable] = None,
) -> None:
    """
    Show dialog for completing a time entry with comment and DevOps integration.
    
    Args:
        customer_id: Customer ID for the time entry
        project_id: Project ID for the time entry
        on_save_callback: Async function to call on save with (git_id, comment, store_to_devops)
        on_delete_callback: Async function to call on delete
        on_close_callback: Function to call on close/cancel
    """
    LOG = GlobalRegistry.get("LOG")
    QE = GlobalRegistry.get("QE")
    DO = GlobalRegistry.get("DO")
    
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
                        match["display_name"].iloc[0]
                        if not match.empty
                        else None
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
                    LOG.log_msg(
                        "DEBUG",
                        f"Time entry save: git_id={git_id_val}, devops={store_to_devops}, "
                        f"customer={customer_id}, project={project_id}",
                    )
                
                if on_save_callback:
                    await on_save_callback(git_id_val, comment_input.value, store_to_devops)
                
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


async def show_confirmation_dialog(
    title: str,
    message: str,
    on_confirm=None,
    confirm_text: str = "Confirm",
    cancel_text: str = "Cancel",
    confirm_color: str = "primary",
) -> None:
    """
    Show a simple confirmation dialog.
    
    Args:
        title: Dialog title
        message: Confirmation message
        on_confirm: Async function to call on confirmation
        confirm_text: Text for confirm button
        cancel_text: Text for cancel button
        confirm_color: Color for confirm button (primary, negative, positive, etc.)
    """
    with ui.dialog() as dialog, ui.card():
        ui.label(title).classes("text-h6 mb-2")
        ui.label(message).classes("mb-4")
        
        async def handle_confirm():
            if on_confirm:
                await on_confirm()
            dialog.close()
        
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(cancel_text, on_click=dialog.close).props("flat")
            ui.button(confirm_text, on_click=handle_confirm).props(f"color={confirm_color}")
    
    dialog.open()
