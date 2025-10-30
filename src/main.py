from nicegui import events, ui
from nicegui.events import KeyEventArguments
from . import helpers
from .helpers import UI_STYLES
import asyncio
from .globals import (
    Logger,
    AddData,
    QueryEngine,
    DevOpsEngine,
    DevOpsTag,
    SaveData,
    generate_sync_sql,
)
from datetime import datetime
import threading
import tempfile
import os
import yaml
import re
import html
from .globals import GlobalRegistry

CONFIG_FOLDER = "config"


## Config Setup ##
def setup_config():
    global \
        config_ui, \
        config_data, \
        config_query, \
        config_devops_contacts, \
        DEVOPS_TAGS, \
        DEBUG_MODE, \
        MAIN_DB

    with open(f"{CONFIG_FOLDER}/config_settings.yml") as f:
        fields = yaml.safe_load(f)
    DEBUG_MODE = fields.get("debug_mode", False)
    MAIN_DB = fields.get("db_name", "data_dpg.db")
    print(f"Config loaded: DB={MAIN_DB}, Debug={DEBUG_MODE}")

    with open(f"{CONFIG_FOLDER}/config_ui.yml") as f:
        fields = yaml.safe_load(f)
    config_ui = fields
    with open(f"{CONFIG_FOLDER}/config_data.yml") as f:
        fields = yaml.safe_load(f)
    config_data = fields
    with open(f"{CONFIG_FOLDER}/config_query.yml") as f:
        fields = yaml.safe_load(f)
    config_query = fields

    # Load DevOps contacts config (optional - use template if not exists)
    contacts_file = f"{CONFIG_FOLDER}/devops_contacts.yml"
    if os.path.exists(contacts_file):
        with open(contacts_file) as f:
            config_devops_contacts = yaml.safe_load(f)
        print(
            f"DevOps contacts loaded: {len(config_devops_contacts.get('customers', {}))} customers"
        )
    else:
        print(f"WARNING: {contacts_file} not found. Using empty defaults.")
        print(
            "Copy devops_contacts.yml.template to devops_contacts.yml and customize it."
        )
        config_devops_contacts = {
            "customers": {},
            "default": {"contacts": [], "assignees": []},
        }

    DEVOPS_TAGS = []
    for f in config_data["devops_tags"]:
        DEVOPS_TAGS.append(DevOpsTag(**f))


## UI SETUP ##
def ui_time_tracking():
    with ui.grid(columns="160px 550px 240px").classes("w-full gap-0 items-center"):
        ui.label("Time Span").classes("items-center")
        time_options = ["Day", "Week", "Month", "Year", "All-Time", "Custom"]
        selected_time = (
            ui.radio(time_options, value="Day").props("inline").classes("items-center")
        )
        selected_time
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
            ui.radio(["Time", "Bonus"], value="Time")
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
            return

        async def show_uncheck_popup():
            checkbox = event.sender
            with ui.dialog().props("persistent") as popup:
                with ui.card().classes(UI_STYLES.get_widget_width("extra_wide")):
                    # Query project/customer info
                    sql_query = f"""
                    select distinct t.customer_name, t.project_name, p.git_id from time t
                    left join projects p on p.project_id = t.project_id
                    where t.customer_id = {customer_id}
                    and t.project_id = {project_id}
                    """
                    df = await QE.query_db(sql_query)
                    c_name = df.iloc[0]["customer_name"] if not df.empty else "Unknown"
                    p_name = df.iloc[0]["project_name"] if not df.empty else "Unknown"
                    git_id = df.iloc[0]["git_id"] if not df.empty else 0
                    has_git_id = git_id is not None and git_id > 0

                    ui.label(f"{p_name} - {c_name}").classes("text-h6 w-full")

                    # DevOps connection check
                    has_devops = bool(
                        hasattr(DO, "manager")
                        and DO.manager
                        and hasattr(DO.manager, "clients")
                        and c_name in DO.manager.clients
                    )
                    id_input = None
                    id_checkbox = None
                    if has_devops:
                        id_options = DO.df[(DO.df["customer_name"] == c_name)][
                            ["display_name", "id"]
                        ].dropna()
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

                        with ui.row().classes(
                            "w-full items-center justify-between -mt-2"
                        ):

                            def toggle_switch():
                                id_checkbox.value = not id_checkbox.value
                                id_checkbox.update()

                            ui.label("Store to DevOps").on(
                                "click", toggle_switch
                            ).classes("cursor-pointer")
                            id_checkbox = ui.switch(value=has_git_id).props("dense")

                    comment_input = ui.textarea(
                        label="Comment", placeholder="What work was done?"
                    ).classes("w-full -mt-2")

                    def close_popup():
                        nonlocal ignore_next_checkbox_event
                        ignore_next_checkbox_event = True
                        checkbox.set_value(True)
                        popup.close()

                    async def save_popup():
                        git_id_val = None
                        store_to_devops = False
                        if has_devops and id_input is not None:
                            git_id_str = id_input.value
                            if git_id_str and isinstance(git_id_str, str):
                                match = re.search(r":\s*(\d+)\s*-", git_id_str)
                                if match:
                                    try:
                                        git_id_val = int(match.group(1))
                                    except ValueError:
                                        git_id_val = None
                            store_to_devops = (
                                id_checkbox.value if id_checkbox is not None else False
                            )

                        LOG.log_msg(
                            "DEBUG",
                            f"Saved: {git_id_val}, {store_to_devops}, {comment_input.value}, customer_id: {customer_id}, project_id: {project_id}",
                        )
                        run_async_task(
                            lambda: asyncio.run(
                                QE.function_db(
                                    "insert_time_row",
                                    int(customer_id),
                                    int(project_id),
                                    git_id=git_id_val,
                                    comment=comment_input.value,
                                )
                            )
                        )

                        sql_code = f"select customer_name from customers where customer_id = {customer_id}"
                        customer_name = await QE.query_db(sql_code)
                        if (
                            has_devops
                            and store_to_devops
                            and git_id_val
                            and git_id_val > 0
                        ):
                            if DO.manager:
                                status, msg = DO.manager.save_comment(
                                    customer_name=customer_name.iloc[0][
                                        "customer_name"
                                    ],
                                    comment=comment_input.value,
                                    git_id=git_id_val,
                                )
                                col = "positive" if status else "negative"
                                ui.notify(msg, color=col)
                        popup.close()

                    async def delete_popup():
                        await QE.function_db(
                            "delete_time_row", int(customer_id), int(project_id)
                        )
                        ui.notify("Entry deleted", color="negative")
                        popup.close()

                    with ui.row().classes("justify-end gap-2"):
                        btn_classes = UI_STYLES.get_widget_width("button")
                        ui.button("Save", on_click=save_popup).classes(btn_classes)
                        ui.button("Delete", on_click=delete_popup).props(
                            "color=negative"
                        ).classes(f"q-btn--warning {btn_classes}")
                        ui.button("Close", on_click=close_popup).props("flat").classes(
                            btn_classes
                        )
            popup.open()

        await show_uncheck_popup()

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

    global render_ui

    async def render_ui():
        """Render the main time tracking UI, grouped by customer and project."""
        value_labels.clear()
        customer_total_labels.clear()
        df = await get_ui_data()
        container.clear()

        def get_total_string(customer_id):
            if "time" in radio_display_selection.value.lower():
                total = df[df["customer_id"] == customer_id]["total_time"].sum()
                return f"{total:.2f} h"
            else:
                total = df[df["customer_id"] == customer_id]["user_bonus"].sum()
                return f"{total:.2f} SEK"

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
                    "display: grid; grid-template-columns: 20px 1fr 100px; align-items: center; margin-bottom:2px; min-height:20px;"
                )
            ):
                ui.checkbox(
                    on_change=make_callback(
                        project["customer_id"], project["project_id"]
                    ),
                    value=initial_state,
                )
                ui.label(str(project["project_name"])).classes("ml-2 truncate")
                total_string = (
                    f"{project['total_time']} h"
                    if "time" in radio_display_selection.value.lower()
                    else f"{project['user_bonus']} SEK"
                )
                value_label = (
                    ui.label(f"{total_string}")
                    .classes("text-grey text-right whitespace-nowrap w-full")
                    .style("max-width:100px; overflow-x:auto;")
                )
                value_labels.append((value_label, customer_id, project["project_id"]))

        async def make_customer_card(customer_id, customer_name, group):
            with ui.card().classes(UI_STYLES.get_card_classes("xs", "card_padded")):
                with (
                    ui.column()
                    .classes("items-start")
                    .style(
                        "flex:1 1 320px; min-width:320px; max-width:420px; margin:0 12px; box-sizing:border-box;"
                    )
                ):
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
                .style("flex-wrap:nowrap; width:100%; max-width:1800px; margin:0 auto;")
            ):
                # Run customer cards in series for UI consistency
                for (customer_id, customer_name), group in customers:
                    await make_customer_card(customer_id, customer_name, group)

    async def update_ui():
        """Update the UI labels for project and customer totals based on the latest data."""
        df = await get_ui_data()

        def get_time_string(row):
            if "time" in radio_display_selection.value.lower():
                return f"{row['total_time']} h"
            else:
                return f"{row['user_bonus']} SEK"

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
            if "time" in radio_display_selection.value.lower():
                total = df[df["customer_id"] == customer_id]["total_time"].sum()
                label_total.text = f"{total:.2f} h"
            else:
                total = df[df["customer_id"] == customer_id]["user_bonus"].sum()
                label_total.text = f"{total:.2f} SEK"

    asyncio.run(render_ui())


def ui_add_data():
    asyncio.run(AD.refresh())

    # --- Data Preparation Functions (entity-specific logic) ---

    def prep_customer_data(tab_type, fields):
        """Prepare data sources for customer tabs."""
        active_data = helpers.filter_df(AD.df, {"c_current": 1})

        if tab_type == "Add":
            return {"date": None}

        elif tab_type == "Update":
            customer_names = helpers.get_unique_list(active_data, "customer_name")
            org_urls = {}
            pat_tokens = {}
            new_customer_names = {}

            for customer in customer_names:
                filtered = helpers.filter_df(AD.df, {"customer_name": customer})
                org_urls[customer] = helpers.get_unique_list(filtered, "org_url")
                pat_tokens[customer] = helpers.get_unique_list(filtered, "pat_token")
                new_customer_names[customer] = [customer]

            return {
                "customer_data": customer_names,
                "new_customer_name": new_customer_names,
                "org_url": org_urls,
                "pat_token": pat_tokens,
            }

        elif tab_type == "Disable":
            customer_names = helpers.get_unique_list(active_data, "customer_name")
            return {"customer_data": customer_names}

        elif tab_type == "Reenable":
            customer_names = helpers.get_unique_list(active_data, "customer_name")
            candidate_names = helpers.filter_df(
                AD.df,
                {"c_current": 0},
                return_as="distinct_list",
                column="customer_name",
            )
            reenable_names = sorted(list(set(candidate_names) - set(customer_names)))
            return {"customer_data": reenable_names}

        return {}

    def prep_project_data(tab_type, fields):
        """Prepare data sources for project tabs."""
        active_data = helpers.filter_df(AD.df, {"c_current": 1})
        active_customer_names = helpers.get_unique_list(active_data, "customer_name")

        if tab_type == "Add":
            return {"customer_data": active_customer_names}

        elif tab_type == "Update":
            project_names = {}
            new_project_name = {}
            new_git_id = {}

            for customer in active_customer_names:
                filtered = helpers.filter_df(
                    active_data, {"customer_name": customer, "p_current": 1}
                )
                project_names[customer] = helpers.get_unique_list(
                    filtered, "project_name"
                )
                for project in project_names[customer]:
                    filtered_cust = helpers.filter_df(
                        filtered, {"project_name": project}
                    )
                    new_project_name[project] = [project]
                    new_git_id[project] = helpers.get_unique_list(
                        filtered_cust, "git_id"
                    )

            return {
                "customer_data": active_customer_names,
                "project_names": project_names,
                "new_project_name": new_project_name,
                "new_git_id": new_git_id,
            }

        elif tab_type == "Disable":
            project_names = {}
            for customer in active_customer_names:
                filtered = helpers.filter_df(
                    active_data, {"customer_name": customer, "p_current": 1}
                )
                project_names[customer] = helpers.get_unique_list(
                    filtered, "project_name"
                )

            return {
                "customer_data": active_customer_names,
                "project_names": project_names,
            }

        elif tab_type == "Reenable":
            project_names = {}
            for customer in active_customer_names:
                filtered = helpers.filter_df(
                    active_data, {"customer_name": customer, "p_current": 0}
                )
                project_names[customer] = helpers.get_unique_list(
                    filtered, "project_name"
                )

            return {
                "customer_data": active_customer_names,
                "project_names": project_names,
            }

        return {}

    def prep_bonus_data(tab_type, fields):
        """Prepare data sources for bonus tabs."""
        # Bonus tab only has "Add" and doesn't need any dynamic data sources
        return {}

    def prep_devops_data(tab_type, fields):
        """Prepare data sources for DevOps Work Items tabs."""
        if DO.df is None:
            return {}

        customer_names = helpers.get_unique_list(DO.df, "customer_name")
        work_items = {}
        parent_names = {}

        for customer in customer_names:
            filtered = helpers.filter_df(DO.df, {"customer_name": customer})
            work_items[customer] = [
                row["display_name"] for _, row in filtered.iterrows()
            ]

            # Get parent items for different work item types
            epics_filtered = helpers.filter_df(
                DO.df, {"customer_name": customer, "type": "Epic"}
            )
            features_filtered = helpers.filter_df(
                DO.df, {"customer_name": customer, "type": ["Epic", "Feature"]}
            )
            parent_names[customer] = {
                "Epic": [],  # Epics have no parents
                "Feature": [
                    row["display_name"] for _, row in epics_filtered.iterrows()
                ],  # Features parent to Epics
                "User Story": [
                    row["display_name"] for _, row in features_filtered.iterrows()
                ],  # User Stories parent to Epics/Features
            }

        if tab_type == "Add":
            # Prepare customer-specific contacts and assignees
            contact_persons = {}
            assignees = {}
            default_assignee = {}

            for customer in customer_names:
                # Get customer-specific data from config
                customer_data = config_devops_contacts.get("customers", {}).get(
                    customer, {}
                )
                default_data = config_devops_contacts.get("default", {})

                # Use customer-specific contacts, or fall back to defaults
                contact_persons[customer] = customer_data.get(
                    "contacts", default_data.get("contacts", [])
                )
                assignees[customer] = customer_data.get(
                    "assignees", default_data.get("assignees", [])
                )
                # Get the default assignee for this customer
                default_assignee[customer] = customer_data.get("default_assignee", None)

            return {
                "customer_data": customer_names,
                "work_items": work_items,
                "parent_names": parent_names,
                "devops_tags": DEVOPS_TAGS,
                "contact_persons": contact_persons,
                "assignees": assignees,
                "default_assignee": default_assignee,
            }
        elif tab_type == "Update":
            # Prepare customer-specific assignees for Update tab
            assignees = {}
            for customer in customer_names:
                # Get customer-specific data from config
                customer_data = config_devops_contacts.get("customers", {}).get(
                    customer, {}
                )
                default_data = config_devops_contacts.get("default", {})

                # Use customer-specific assignees, or fall back to defaults
                assignees[customer] = customer_data.get(
                    "assignees", default_data.get("assignees", [])
                )

            return {
                "customer_data": customer_names,
                "work_items": work_items,
                "assignees": assignees,
            }

        return {}

    # --- Wrapper Functions (Simple Entities) ---

    def build_customer_tab_panel(tab_type, container_dict):
        """Build customer tab panel using generic builder."""
        helpers.build_generic_tab_panel(
            entity_name="customer",
            tab_type=tab_type,
            container_dict=container_dict,
            config_source=config_ui,
            data_prep_func=prep_customer_data,
            on_success_callback=lambda: AD.refresh(),
        )

    def build_project_tab_panel(tab_type, container_dict):
        """Build project tab panel using generic builder."""
        helpers.build_generic_tab_panel(
            entity_name="project",
            tab_type=tab_type,
            container_dict=container_dict,
            config_source=config_ui,
            data_prep_func=prep_project_data,
            on_success_callback=lambda: AD.refresh(),
        )

    def build_bonus_tab_panel(tab_type, container_dict):
        """Build bonus tab panel using generic builder."""
        helpers.build_generic_tab_panel(
            entity_name="bonus",
            tab_type=tab_type,
            container_dict=container_dict,
            config_source=config_ui,
            data_prep_func=prep_bonus_data,
            on_success_callback=lambda: AD.refresh(),
        )

    def add_work_item(widgets):
        """Create a work item (Epic, Feature, or User Story) based on the selected type."""
        wid = helpers.parse_widget_values(widgets)

        work_item_type = wid["work_item_type"]
        title = wid["work_item_title"]
        description = wid.get("description_editor", "")

        # Build additional fields
        additional_fields = {
            "System.State": wid["state"],
            "System.Tags": ", ".join([t for t in wid.get("tags", [])]),
            "Microsoft.VSTS.Common.Priority": int(wid["priority"]),
            "System.AssignedTo": wid.get("assigned_to", ""),
        }

        # Handle parent relationship (only for Features and User Stories)
        parent_id = None
        if wid.get("parent_name") and work_item_type in ["Feature", "User Story"]:
            parent_id = int(helpers.extract_devops_id(wid["parent_name"]))

        # Map work item type to DevOps helper function
        helper_function_map = {
            "Epic": "create_epic",
            "Feature": "create_feature",
            "User Story": "create_user_story",
        }

        helper_function = helper_function_map.get(work_item_type, "create_user_story")

        success, message = DO.devops_helper(
            helper_function,
            customer_name=wid["customer_name"],
            title=title,
            description=description,
            additional_fields=additional_fields,
            markdown=True,  # wid.get("use_markdown", True)
            parent=parent_id,
        )
        state = "INFO" if success else "ERROR"
        LOG.log_msg(state, message)
        return success, message

    async def update_work_item_description(widgets):
        """Save the updated description back to DevOps."""
        c_name = widgets["customer_name"].value
        work_item_display = widgets["work_item"].value
        work_item_id = helpers.extract_devops_id(work_item_display)
        description = widgets["description_editor"].value or ""

        # Determine if it's markdown based on the editor's language
        is_markdown = (
            getattr(widgets.get("description_editor"), "language", "markdown")
            == "markdown"
        )

        if DO and DO.manager:
            status, msg = DO.manager.set_description(
                c_name, work_item_id, description, markdown=is_markdown
            )
            if status:
                LOG.log_msg("INFO", f"Description updated for work item {work_item_id}")
                return (
                    True,
                    f"Description updated successfully for work item {work_item_id}",
                )
            else:
                LOG.log_msg("ERROR", f"Failed to update description: {msg}")
                return False, f"Failed to update: {msg}"
        return False, "DevOps manager not available"

    async def update_work_item(widgets):
        """Save the updated work item fields back to DevOps."""
        c_name = widgets["customer_name"].value
        work_item_display = widgets["work_item"].value
        work_item_id = helpers.extract_devops_id(work_item_display)

        # Collect all fields that have values
        fields_to_update = {}

        # Description (always present)
        description = widgets["description_editor"].value or ""
        if description:
            fields_to_update["System.Description"] = description

        # State
        state = widgets.get("state")
        if state and state.value:
            fields_to_update["System.State"] = state.value

        # Assigned To
        assigned_to = widgets.get("assigned_to")
        if assigned_to and assigned_to.value:
            fields_to_update["System.AssignedTo"] = assigned_to.value

        # Priority
        priority = widgets.get("priority")
        if priority and priority.value:
            fields_to_update["Microsoft.VSTS.Common.Priority"] = int(priority.value)

        # Determine if description is markdown based on the editor's language
        is_markdown = (
            getattr(widgets.get("description_editor"), "language", "markdown")
            == "markdown"
        )

        if DO and DO.manager:
            status, msg = DO.manager.update_work_item_fields(
                c_name, work_item_id, fields_to_update, markdown=is_markdown
            )
            if status:
                LOG.log_msg("INFO", f"Work item {work_item_id} updated successfully")
                return (
                    True,
                    f"Work item {work_item_id} updated successfully",
                )
            else:
                LOG.log_msg("ERROR", f"Failed to update work item: {msg}")
                return False, f"Failed to update: {msg}"
        return False, "DevOps manager not available"

    def build_work_item_tab_panel(tab_type, container_dict):
        """Build work item tab panel using generic builder with DevOps-specific handlers."""

        # Custom handlers for DevOps operations
        custom_handlers = {
            "add_work_item": add_work_item,
            "update_work_item_description": update_work_item_description,
            "update_work_item": update_work_item,
        }

        # Render functions for HTML preview
        render_functions = {"render_and_sanitize": helpers.render_and_sanitize_markdown}

        # Set container size based on tab type - Update tab needs more space for editor/preview
        container_size = "xxl" if tab_type == "Update" else "lg"

        # Use generic builder and get back the widgets
        widgets = helpers.build_generic_tab_panel(
            entity_name="devops_work_item",
            tab_type=tab_type,
            container_dict=container_dict,
            config_source=config_ui,
            data_prep_func=prep_devops_data,
            custom_handlers=custom_handlers,
            render_functions=render_functions,
            container_size=container_size,
        )

        # Add special event handlers for Update tab (description editor/preview and loading)
        if tab_type == "Update" and widgets:
            editor_widget = widgets.get("description_editor")
            preview_html = widgets.get("description_preview")
            work_item_widget = widgets.get("work_item")
            customer_widget = widgets.get("customer_name")
            state_widget = widgets.get("state")
            assigned_to_widget = widgets.get("assigned_to")
            priority_widget = widgets.get("priority")

            # Set up editor preview update
            if editor_widget and preview_html:

                def update_preview():
                    preview_html.set_content(
                        helpers.render_and_sanitize_markdown(editor_widget.value)
                    )

                editor_widget.on_value_change(update_preview)

            # Set up work item details loader
            if work_item_widget and customer_widget and editor_widget and preview_html:

                async def load_work_item_details(e):
                    """Load all work item details when work item is selected."""
                    c_name = customer_widget.value
                    work_item_display = work_item_widget.value

                    if not c_name or not work_item_display:
                        return

                    work_item_id = helpers.extract_devops_id(work_item_display)

                    if DO.manager:
                        # Get full work item details
                        status, details = DO.manager.get_work_item_details(
                            customer_name=c_name, work_item_id=work_item_id
                        )

                        if status:
                            # Update description
                            description_raw = details.get("description", "")

                            # Check if the content appears to be HTML (contains HTML tags)
                            is_html_content = bool(
                                description_raw
                                and ("<" in description_raw and ">" in description_raw)
                            )

                            if is_html_content:
                                # Convert HTML to markdown for better readability in editor
                                description_clean = helpers.convert_html_to_markdown(
                                    description_raw
                                )
                            else:
                                # Just unescape HTML entities for plain text/markdown content
                                description_clean = html.unescape(description_raw)

                            editor_widget.value = description_clean
                            editor_widget.update()
                            preview_html.set_content(
                                helpers.render_and_sanitize_markdown(description_clean)
                            )

                            # Update other fields
                            if state_widget and details.get("state"):
                                try:
                                    state_value = details["state"]
                                    # Try both methods for setting the value
                                    state_widget.set_value(state_value)
                                    state_widget.value = state_value
                                except Exception as e:
                                    LOG.log_msg(
                                        "WARNING", f"Failed to set state widget: {e}"
                                    )

                            if assigned_to_widget and details.get("assigned_to"):
                                try:
                                    # Get the raw assigned_to field from DevOps to extract email
                                    assigned_to_raw = details.get("assigned_to_raw")
                                    assigned_to_display = details["assigned_to"]

                                    # Try to use the email address (uniqueName) if available
                                    if assigned_to_raw and isinstance(
                                        assigned_to_raw, dict
                                    ):
                                        assigned_to_value = assigned_to_raw.get(
                                            "uniqueName", assigned_to_display
                                        )
                                    else:
                                        assigned_to_value = assigned_to_display

                                    # Check if the value is in the dropdown options
                                    widget_options = getattr(
                                        assigned_to_widget, "options", []
                                    )
                                    if assigned_to_value in widget_options:
                                        assigned_to_widget.set_value(assigned_to_value)
                                        assigned_to_widget.value = assigned_to_value
                                    else:
                                        # For combobox widgets (with_input: true), we can set custom values
                                        assigned_to_widget.set_value(
                                            assigned_to_display
                                        )
                                        assigned_to_widget.value = assigned_to_display
                                except Exception as e:
                                    LOG.log_msg(
                                        "WARNING",
                                        f"Failed to set assigned_to widget: {e}",
                                    )

                            if priority_widget and details.get("priority") is not None:
                                try:
                                    # Convert to integer to match widget options
                                    priority_value = int(details["priority"])
                                    # Try both methods for setting the value
                                    priority_widget.set_value(priority_value)
                                    priority_widget.value = priority_value
                                except Exception as e:
                                    LOG.log_msg(
                                        "WARNING", f"Failed to set priority widget: {e}"
                                    )
                        else:
                            ui.notify(
                                f"Failed to load work item details: {details}",
                                color="negative",
                            )
                            LOG.log_msg(
                                "ERROR", f"Failed to load work item details: {details}"
                            )

                work_item_widget.on("update:model-value", load_work_item_details)

        # Add special event handlers for Add tab (auto-populate source and contact)
        if tab_type == "Add" and widgets:
            editor_widget = widgets.get("description_editor")
            preview_widget = widgets.get("description_preview")
            source_widget = widgets.get("source")
            contact_widget = widgets.get("contact_person")

            # Initialize the preview with the initial editor content
            if editor_widget and preview_widget:
                initial_content = editor_widget.value or ""
                preview_widget.set_content(
                    helpers.render_and_sanitize_markdown(initial_content)
                )

            if editor_widget and (source_widget or contact_widget):
                import re

                def update_editor_field(field_name, new_value):
                    """Update a specific field in the markdown editor."""
                    current_text = editor_widget.value or ""

                    # Debug: log the current text to see what we're working with
                    LOG.log_msg(
                        "DEBUG",
                        f"Updating field '{field_name}' with value '{new_value}'",
                    )
                    LOG.log_msg(
                        "DEBUG", f"Current editor content:\n{repr(current_text[:200])}"
                    )

                    # Match the field and update its value (only the content after the field name)
                    # Pattern: **FieldName:** followed by optional spaces/content until newline
                    # We need to match the entire line including trailing whitespace
                    pattern = rf"^(\*\*{re.escape(field_name)}:\*\*)(.*)$"

                    # Check if the pattern exists in the text (using MULTILINE flag)
                    match = re.search(pattern, current_text, re.MULTILINE)
                    if match:
                        LOG.log_msg(
                            "DEBUG", f"Pattern matched! Groups: {match.groups()}"
                        )
                        # Replace with the field name followed by a space and the new value
                        replacement = rf"\1 {new_value}"
                        updated_text = re.sub(
                            pattern,
                            replacement,
                            current_text,
                            count=1,
                            flags=re.MULTILINE,
                        )
                    else:
                        # If pattern not found, just return without updating
                        LOG.log_msg(
                            "WARNING", f"Pattern for '{field_name}' not found in editor"
                        )
                        LOG.log_msg("DEBUG", f"Searched for pattern: {pattern}")
                        return

                    editor_widget.value = updated_text
                    editor_widget.update()

                    # Also update the preview
                    if preview_widget:
                        preview_widget.set_content(
                            helpers.render_and_sanitize_markdown(updated_text)
                        )

                if source_widget:

                    def on_source_change(e):
                        # Get the new value from the widget directly
                        new_value = source_widget.value or ""
                        update_editor_field("Source", new_value)

                    source_widget.on("update:model-value", on_source_change)

                if contact_widget:

                    def on_contact_change(e):
                        # Get the new value from the widget directly
                        new_value = contact_widget.value or ""
                        update_editor_field("Contact", new_value)

                    contact_widget.on("update:model-value", on_contact_change)

    def build_database_compare():
        def handle_upload(e: events.UploadEventArguments):
            ui.notify(f"File uploaded: {e.name}", color="positive")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
                tmp.write(e.content.read())
                uploaded_path = tmp.name

            sync_sql = generate_sync_sql(MAIN_DB, uploaded_path)
            db_deltas.set_content(sync_sql)
            db_deltas.update()
            os.remove(uploaded_path)  # Clean up temp file

        with ui.card().classes(UI_STYLES.get_card_classes("xs", "card")):
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

    def build_database_update():
        uploaded_db_path = None
        original_db_filename = None

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
            import sqlite3

            try:
                conn = sqlite3.connect(uploaded_db_path)

                cursor = conn.cursor()
                query = (
                    sql_input.value if hasattr(sql_input, "value") else sql_input.text
                )
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
                        + "\n".join(
                            ["\t".join(str(cell) for cell in row) for row in rows]
                        )
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

        with ui.card().classes(UI_STYLES.get_card_classes("xs", "card")):
            ui.label("Upload a .db file to run SQL queries on.").classes(
                UI_STYLES.get_layout_classes("title").replace("mb-4", "mb-0 dense")
            )
            ui.upload(on_upload=handle_upload).props("accept=.db").classes(
                "q-pa-xs q-ma-xs mb-2"
            )
            with ui.row().classes("w-full mb-2"):
                ui.button("Run SQL", on_click=run_sql).classes("mr-2")

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

                ui.button("Download DB", on_click=download_db)

        sql_input = ui.codemirror(
            "-- Enter SQL query here --",
            language="SQLite",
            theme="dracula",
        ).classes(UI_STYLES.get_widget_style("code_display", "small")["classes"])

        result_box = ui.code("-- Results will appear here --", language="sql").classes(
            UI_STYLES.get_widget_style("code_display", "medium")["classes"]
        )

    tab_list = {}
    vertical_tab_entries = [i for i in config_ui]

    with ui.splitter(value=20).classes("w-full h-full") as splitter:
        with splitter.before:
            with ui.tabs().props("vertical").classes("w-full") as main_tabs:
                for tab in vertical_tab_entries:
                    meta_data = config_ui[tab].get("meta", {})
                    tab_list[tab] = {
                        "tab": ui.tab(
                            meta_data.get("friendly_name", tab.capitalize()),
                            icon=meta_data.get("icon", "folder"),
                        ),
                        "name": tab,
                        "tab_list": [],
                        "tab_container": {},
                        "build_function": meta_data.get("build_function", None),
                        "friendly_name": meta_data.get(
                            "friendly_name", tab.capitalize()
                        ),
                    }
                tab_database = ui.tab("Database", icon="storage")
        with splitter.after:
            with (
                ui.tab_panels(
                    main_tabs, value=tab_list[vertical_tab_entries[0]]["friendly_name"]
                )
                .props("vertical")
                .classes("w-full h-full")
            ):

                async def on_tab_change(e, function, container):
                    tab_type = e.args
                    await AD.refresh()
                    function(tab_type, container)

                # Define function map after all functions are available
                function_map = {
                    "build_customer_tab_panel": build_customer_tab_panel,
                    "build_project_tab_panel": build_project_tab_panel,
                    "build_bonus_tab_panel": build_bonus_tab_panel,
                    "build_work_item_tab_panel": build_work_item_tab_panel,
                }

                for tab_dict in tab_list.values():
                    tab_names = [
                        i.capitalize()
                        for i in helpers.get_ui_elements(config_ui[tab_dict["name"]])
                    ]

                    with ui.tab_panel(tab_dict["tab"]):
                        with ui.tabs().classes("mb-2") as temp_tab:
                            for name in tab_names:
                                tab_dict["tab_list"].append(ui.tab(name))
                        # Only create tab_panels if there are tabs to display
                        if tab_dict["tab_list"]:
                            with ui.tab_panels(temp_tab, value=tab_dict["tab_list"][0]):
                                for i, name in enumerate(tab_names):
                                    with ui.tab_panel(tab_dict["tab_list"][i]):
                                        function_map[tab_dict["build_function"]](
                                            name, tab_dict["tab_container"]
                                        )
                            temp_tab.on(
                                "update:model-value",
                                lambda e,
                                function=function_map[tab_dict["build_function"]],
                                container=tab_dict["tab_container"]: on_tab_change(
                                    e,
                                    function,
                                    container,
                                ),
                            )

                # Database
                with ui.tab_panel(tab_database):
                    with ui.tabs().classes("mb-2") as database_tabs:
                        tab_add = ui.tab("Schema Compare")
                        tab_update = ui.tab("Update DB")

                    with ui.tab_panels(database_tabs, value=tab_add):
                        with ui.tab_panel(tab_add):
                            build_database_compare()
                        with ui.tab_panel(tab_update):
                            build_database_update()

    # DevOps Work Item Functions - moved from DevOps Settings to be used in Data Input


def ui_query_editor():
    asyncio.run(QE.refresh())

    async def save_custom_query():
        query = editor.value
        try:
            await QE.query_db(query)
        except Exception:
            ui.notify("Query is invalid", color="negative")
            LOG.log_msg("WARNING", "Custom query is invalid and cannot be saved!")
            return

        def close_popup():
            popup.close()

        async def save_popup():
            name = name_input.value.strip()
            if not name:
                ui.notify("Query name required", color="negative")
                LOG.log_msg(
                    "WARNING", "Custom query name is required and cannot be saved!"
                )
                return
            if name in QE.df["query_name"].tolist():
                ui.notify("Query name already exists", color="negative")
                LOG.log_msg(
                    "WARNING", "Custom query name already exists and cannot be saved!"
                )
                return
            await QE.function_db(
                "execute_query",
                "insert into queries (query_name, query_sql) values (?, ?)",
                (name, query),
            )
            ui.notify(f"Query '{name}' saved!", color="positive")
            LOG.log_msg("INFO", f"Custom query '{name}' saved successfully!")
            popup.close()
            await QE.refresh()
            render_query_buttons()

        with ui.dialog() as popup:
            with ui.card().classes(UI_STYLES.get_widget_width("standard")):
                name_input = ui.input("Query Name").classes("w-full")
                with ui.row().classes("justify-between items-center w-full"):
                    ui.button("Save", on_click=save_popup).classes(
                        UI_STYLES.get_layout_classes("button_fixed")
                    )
                    ui.button("Cancel", on_click=close_popup).props("flat").classes(
                        UI_STYLES.get_layout_classes("button_fixed")
                    )
        popup.open()

    async def update_custom_query():
        if len(QE.df[QE.df["is_default"] != 1]["query_name"]) == 0:
            ui.notify("No custom query exists", color="negative")
            LOG.log_msg("WARNING", "No custom query exists to update!")
            return

        query = editor.value
        try:
            await QE.query_db(query)
        except Exception:
            ui.notify("Query is invalid", color="negative")
            LOG.log_msg("WARNING", "Custom query is invalid and cannot be updated!")
            return

        def close_popup():
            popup.close()

        async def save_popup():
            name = name_input.value.strip()
            if not name:
                ui.notify("Select an existing query", color="negative")
                LOG.log_msg("WARNING", "No query name selected for update!")
                return
            await QE.function_db(
                "execute_query",
                "update queries set query_sql = ? where query_name = ?",
                (query, name),
            )
            ui.notify(f"Query '{name}' updated!", color="positive")
            LOG.log_msg("INFO", f"Custom query '{name}' updated successfully!")
            popup.close()
            await QE.refresh()
            render_query_buttons()

        with ui.dialog() as popup:
            with ui.card().classes(UI_STYLES.get_widget_width("standard")):
                name_input = ui.select(
                    options=QE.df[QE.df["is_default"] != 1]["query_name"].tolist(),
                    label="Existing Query",
                ).classes("w-full")
                with ui.row().classes("justify-between items-center w-full"):
                    ui.button("Update", on_click=save_popup).classes(
                        UI_STYLES.get_layout_classes("button_fixed")
                    )
                    ui.button("Cancel", on_click=close_popup).props("flat").classes(
                        UI_STYLES.get_layout_classes("button_fixed")
                    )
        popup.open()

    async def delete_custom_query():
        if len(QE.df[QE.df["is_default"] != 1]["query_name"]) == 0:
            ui.notify("At least one custom query must exist", color="negative")
            return

        def close_popup():
            popup.close()

        async def save_popup():
            name = name_input.value.strip()
            if not name:
                ui.notify("Select an existing query", color="negative")
                LOG.log_msg("WARNING", "No query name selected for deletion!")
                return
            await QE.function_db(
                "execute_query",
                "delete from queries where query_name = ?",
                (name,),
            )
            ui.notify(f"Query '{name}' deleted!", color="positive")
            LOG.log_msg("INFO", f"Custom query '{name}' deleted successfully!")
            popup.close()
            await QE.refresh()
            render_query_buttons()

        with ui.dialog() as popup:
            with ui.card().classes(UI_STYLES.get_widget_width("standard")):
                name_input = ui.select(
                    options=QE.df[QE.df["is_default"] != 1]["query_name"].tolist(),
                    label="Existing Query",
                ).classes("w-full")
                with ui.row().classes("justify-between items-center w-full"):
                    ui.button("Delete", on_click=save_popup).classes(
                        UI_STYLES.get_layout_classes("button_fixed")
                    )
                    ui.button("Cancel", on_click=close_popup).props("flat").classes(
                        UI_STYLES.get_layout_classes("button_fixed")
                    )
        popup.open()

    def add_save_button(save_data, fields, widgets, table_name, pk_data, popup):
        async def on_save():
            required_fields = [
                f["name"] for f in fields if not f.get("optional", False)
            ]
            if not helpers.check_input(widgets, required_fields):
                return
            kwargs = {f["name"]: widgets[f["name"]].value for f in fields}
            # Convert any single-item list in kwargs to a string
            for k, v in kwargs.items():
                if isinstance(v, list):
                    if len(v) == 1:
                        kwargs[k] = v[0]
                    elif len(v) > 1:  ## TODO make nicer
                        raise ValueError(
                            f"Field '{k}' has multiple values: {v}. Only one value is allowed."
                        )

            kwargs["table_name"] = table_name
            kwargs["pk_data"] = pk_data

            await QE.function_db(save_data.function, **kwargs)

            val = (
                ""
                if save_data.main_param == "None"
                else widgets[save_data.main_param].value
            )
            sec_action = (
                ""
                if save_data.secondary_action == "None"
                else save_data.secondary_action
            )
            msg_1, msg_2 = helpers.print_success(
                save_data.main_action,
                val,
                sec_action,
                widgets=widgets,
            )
            LOG.log_msg("INFO", msg_1)
            LOG.log_msg("INFO", msg_2)
            close_popup()

        def close_popup():
            popup.close()

        with ui.row().classes("justify-end gap-2"):
            ui.button(save_data.button_name, on_click=on_save).classes(
                UI_STYLES.get_layout_classes("button_fixed")
            )
            ui.button("Cancel", on_click=close_popup).props("flat").classes(
                UI_STYLES.get_layout_classes("button_fixed")
            )

    with ui.row().classes("justify-between items-center w-full"):
        preset_queries = ui.element()

        def render_query_buttons_group(queries):
            for _, row in queries.iterrows():
                ui.button(
                    row["query_name"],
                    on_click=lambda r=row: editor.set_value(r["query_sql"]),
                ).props("flat dense").classes(
                    UI_STYLES.get_widget_style("query_button", "base")["classes"]
                )

        def render_query_buttons():
            preset_queries.clear()
            with preset_queries:
                with ui.button_group().classes("gap-1"):
                    render_query_buttons_group(QE.df[QE.df["is_default"] == 1])
                    ui.separator().props("vertical").classes("mx-2")
                    render_query_buttons_group(QE.df[QE.df["is_default"] != 1])

        render_query_buttons()

        with ui.button_group().classes("gap-1"):
            for name, function in [
                ("Save Query", save_custom_query),
                ("Update Query", update_custom_query),
                ("Delete Query", delete_custom_query),
            ]:
                ui.button(
                    name,
                    on_click=function,
                ).props("flat dense").classes(
                    UI_STYLES.get_widget_style("query_button", "base")["classes"]
                )

    async def show_row_edit_popup(row_data):
        table_name = helpers.extract_table_name(editor.value)

        if table_name not in ["time", "customers", "projects"]:
            ui.notify(f"Table {table_name} is not registered for editing!")
            return

        base_name = table_name[:-1] if table_name.endswith("s") else table_name
        key_col = f"{base_name}_id"

        if key_col not in row_data:
            ui.notify(
                f"Cannot find {table_name}'s primary key: {key_col} in your query!",
                color="negative",
            )
            return

        pk_data = (key_col, row_data[key_col])

        table_row = await QE.function_db("get_query_edit_data", table_name, pk_data[1])
        table_row = (
            table_row.iloc[0] if not table_row.empty else {}
        )  ## TODO return with error
        projects = await QE.query_db(
            f"select project_name from projects where customer_id = {table_row.get('customer_id', 0)} and is_current = 1"
        )

        fields = config_query["query"][table_name]["fields"]
        action = config_query["query"][table_name]["action"]

        data_sources = {}
        for field in fields:
            # Special handling for project_names in time table
            if table_name == "time":
                data_sources["project_names"] = projects["project_name"].tolist()
                data_sources["default_project"] = table_row.get("project_name", None)

            options_source = field.get("options_source")
            if options_source:
                data_sources[options_source] = table_row.get(options_source, None)

        helpers.assign_dynamic_options(
            fields,
            data_sources=data_sources,
        )

        with ui.dialog() as popup:
            with ui.card().classes(UI_STYLES.get_widget_width("medium")):
                widgets = helpers.make_input_row(fields)
                save_data = SaveData(**action)
                add_save_button(save_data, fields, widgets, table_name, pk_data, popup)
            popup.open()

    async def on_cell_clicked(event):
        row_data = event.args["data"]
        await show_row_edit_popup(row_data)

    ui.label("Query Editors")

    initial_query = QE.df[QE.df["query_name"] == "time"]["query_sql"].values[0]
    editor = ui.codemirror(
        initial_query,
        language="SQLite",
        theme="dracula",
    ).classes("h-48 w-full")
    grid_box = (
        ui.aggrid(
            {
                "columnDefs": [{"field": ""}],
                "rowData": [],
            },
            theme="alpine-dark",
        )
        .classes("h-96 w-full")
        .on(
            "cellClicked",
            on_cell_clicked,
        )
    )

    async def run_code():
        query = editor.value
        try:
            df = await QE.query_db(query)
            if df is not None:
                grid_box.options["columnDefs"] = [
                    {"field": str(col).lower(), "headerName": str(col).lower()}
                    for col in df.columns
                ]
                grid_box.options["rowData"] = df.to_dict(orient="records")
                grid_box.update()
            else:
                with grid_box:
                    ui.notify("Query executed successfully (no result set).")
        except Exception as e:
            with grid_box:
                ui.notify(f"Error: {e}")

    asyncio.run(run_code())

    def handle_key(e: KeyEventArguments):
        if e.key.f5 and not e.key.shift and e.action.keydown:  # Check for F5 key press
            asyncio.create_task(run_code())

    ui.keyboard(on_key=handle_key)

    ### If ever add customization! ###
    # ui.select(editor.supported_languages, label="Language", clearable=True).classes(
    #     "w-32"
    # ).bind_value(editor, "language")
    # ui.select(editor.supported_themes, label="Theme").classes("w-32").bind_value(
    #     editor, "theme"
    # )
    # ui.label().bind_text(editor, "language")
    # ui.label().bind_text(editor, "theme")


def ui_log():
    with ui.card().classes("w-full max-w-[98vw] mx-auto my-8 p-2 h-[76vh]"):
        ui.label("Application Log").classes("text-h5 mb-4")
        log_textarea = ui.html(content="").classes(
            "w-full h-full overflow-auto bg-black text-white p-2 rounded"
        )
        Logger.set_log_textarea(log_textarea)
        LOG.update_log_textarea()


def ui_info():
    with ui.splitter(value=20).classes("w-full h-full") as splitter:
        with splitter.before:
            with ui.tabs().props("vertical").classes("w-full") as info_tabs:
                tab_readme = ui.tab("README", icon="description")
                tab_info = ui.tab("Info", icon="info")
        with splitter.after:
            with ui.tab_panels(info_tabs, value=tab_readme).classes("w-full h-full"):
                with ui.tab_panel(tab_readme):
                    helpers.render_markdown_card("README.md")
                with ui.tab_panel(tab_info):
                    helpers.render_markdown_card("INFO.md")


def setup_ui():
    dark = ui.dark_mode()
    dark.enable()

    with ui.tabs().classes("w-full") as tabs:
        tab_time = ui.tab("Time Tracking")
        tab_data_input = ui.tab("Data Input")
        tab_query_editors = ui.tab("Query Editors")
        tab_log = ui.tab("Log")
        tab_info = ui.tab("Info")

    def on_tab_change(e):
        tab_value = (
            e.args["value"]
            if isinstance(e.args, dict) and "value" in e.args
            else e.args
        )
        if tab_value == tab_time.label:
            asyncio.create_task(render_ui())

    tabs.on("update:model-value", on_tab_change)

    with ui.tab_panels(tabs, value=tab_time).classes("w-full"):
        with ui.tab_panel(tab_time):
            ui_time_tracking()
        with ui.tab_panel(tab_data_input):
            ui_add_data()
        with ui.tab_panel(tab_query_editors):
            ui_query_editor()
        with ui.tab_panel(tab_log):
            ui_log()
        with ui.tab_panel(tab_info):
            ui_info()

    ui.keyboard(on_key=handle_key)


def handle_key(e: KeyEventArguments):
    # if e.key == "f" and not e.action.repeat:
    #     if e.action.keyup:
    #         ui.notify("f was just released")
    #     elif e.action.keydown:
    #         ui.notify("f was just pressed")
    # if e.modifiers.shift and e.action.keydown:
    #     if e.key.arrow_left:
    #         ui.notify("going left")
    1


## Utility to run any function (sync or async) in a separate thread
def run_async_task(func, *args, **kwargs):
    def runner():
        if asyncio.iscoroutinefunction(func):
            asyncio.run(func(*args, **kwargs))
        else:
            func(*args, **kwargs)

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return t


def main():
    global LOG, QE, AD, DO

    setup_config()
    LOG = Logger.get_logger("WorkTimer", debug=DEBUG_MODE)
    LOG.log_msg("INFO", "Starting WorkTimer!")
    DB_LOG = Logger.get_logger("Database", debug=DEBUG_MODE)
    DO_LOG = Logger.get_logger("DevOps", debug=DEBUG_MODE)

    QE = QueryEngine(file_name=MAIN_DB, log_engine=DB_LOG)
    asyncio.run(QE.refresh())  # Initial load of queries

    AD = AddData(query_engine=QE, log_engine=LOG)
    asyncio.run(AD.refresh())

    DO = DevOpsEngine(query_engine=QE, log_engine=DO_LOG)
    asyncio.run(DO.initialize())

    GlobalRegistry.set("LOG", LOG)
    GlobalRegistry.set("QE", QE)
    GlobalRegistry.set("DO", DO)
    GlobalRegistry.set("AD", AD)

    ui.add_head_html("""
    <script>
    document.addEventListener('keydown', function(e) {
        if (e.key === 'F5') {
            e.preventDefault();
        }
    });
    </script>
    """)
    setup_ui()


if __name__ in {"__main__", "__mp_main__"}:
    main()
    ui.run(host="0.0.0.0", port=8080)
