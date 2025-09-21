from nicegui import ui
from nicegui.events import KeyEventArguments
import helpers
import asyncio
from database_new import Database
from devops_new import DevOpsManager
from datetime import date, datetime
from dataclasses import dataclass

debug = True
add_data_df = None
devops_manager = None


@dataclass
class SaveData:
    function: str
    main_action: str
    main_param: str
    secondary_action: str
    button_name: str = "Save"


async def refresh_add_data():
    global add_data_df
    df = await function_db("get_data_input_list")
    add_data_df = df


def main():
    print("Starting WorkTimer!")


## DB SETUP ##
def setup_db(db_file: str):
    Database(db_file).initialize_db()


async def function_db(func_name: str, *args, **kwargs):
    func = getattr(Database.db, func_name)
    return await asyncio.to_thread(func, *args, **kwargs)


async def query_db(query: str):
    return await asyncio.to_thread(Database.db.smart_query, query)


## DEVOPS SETUP ##
async def setup_devops():
    global devops_manager
    df = await query_db(
        "select distinct customer_name, pat_token, org_url from customers where pat_token is not null and org_url is not null"
    )
    devops_manager = DevOpsManager(df)


## UI SETUP ##
def ui_time_tracking():
    with ui.grid(columns="160px 550px 240px").classes("w-full gap-0 items-center"):
        ui.label("Time Span").classes("items-center")
        time_options = ["Day", "Week", "Month", "Year", "All-Time", "Custom"]
        selected_time = (
            ui.radio(time_options, value="Day").props("inline").classes("items-center")
        )
        selected_time
        with ui.input("Date range").classes("w-50 ml-4 items-center") as date_input:
            with ui.menu().props("no-parent-event") as menu:
                date_picker = (
                    ui.date()
                    .props("range")
                    .bind_value(
                        date_input,
                        forward=lambda x: f"{x['from']} - {x['to']}" if x else None,
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

    def set_custom_radio(e):
        if debug:
            ui.notify(f"Date picker selected: {date_input.value}")
        selected_time.value = "Custom"
        asyncio.create_task(update_ui())

    def on_radio_time_change(e):
        if debug:
            ui.notify(f"Radio Date selected: {selected_time.value}")
        date_input.value = helpers.get_range_for(selected_time.value)
        asyncio.create_task(update_ui())

    def on_radio_type_change(e):
        if debug:
            ui.notify(f"Radio Type selected: {radio_display_selection.value}")
        asyncio.create_task(update_ui())

    date_input.value = helpers.get_range_for(selected_time.value)
    date_input.on("update:model-value", set_custom_radio)
    date_picker.on("update:model-value", set_custom_radio)
    selected_time.on("update:model-value", on_radio_time_change)
    radio_display_selection.on("update:model-value", on_radio_type_change)

    container = ui.element()

    async def on_checkbox_change(event, checked, customer_id, project_id):
        global devops_manager
        if checked:
            if debug:
                ui.notify(
                    f"Checkbox status: {checked}, customer_id: {customer_id}, project_id: {project_id}",
                    close_button="OK",
                )
            await function_db("insert_time_row", int(customer_id), int(project_id))
        else:
            # Show a centered popup/modal with input and three buttons
            checkbox = event.sender
            with ui.dialog().props("persistent") as popup:
                with ui.card().classes("w-96"):
                    ui.label(
                        f"Project {project_id} for Customer {customer_id}"
                    ).classes("text-h6")
                    id_input = ui.number(label="Git-ID", value=0, step=1, format="%.0f")
                    id_checkbox = ui.checkbox("Store to DevOps")
                    comment_input = ui.textarea(
                        label="Comment", placeholder="What work was done?"
                    )

                    def close_popup():
                        popup.close()
                        checkbox.value = True

                    async def save_popup():
                        if debug:
                            ui.notify(
                                f"Saved: {int(id_input.value)}, {id_checkbox.value}, {comment_input.value}, customer_id: {customer_id}, project_id: {project_id}"
                            )
                        await function_db(
                            "insert_time_row",
                            int(customer_id),
                            int(project_id),
                            git_id=int(id_input.value),
                            comment=comment_input.value,
                        )
                        sql_code = f"select customer_name from customers where customer_id = {customer_id}"
                        customer_name = await query_db(sql_code)
                        if id_checkbox.value and int(id_input.value) > 0:
                            if devops_manager:
                                msg = devops_manager.save_comment(
                                    customer_name=customer_name.iloc[0][
                                        "customer_name"
                                    ],
                                    comment=comment_input.value,
                                    git_id=int(id_input.value),
                                )
                                if msg:
                                    ui.notify(
                                        "No valid DevOps connection",
                                        color="negative",
                                        close_button="OK",
                                    )
                                else:
                                    ui.notify(
                                        "Comment stored successfully",
                                        color="positive",
                                        close_button="OK",
                                    )
                        popup.close()

                    async def delete_popup():
                        if debug:
                            ui.notify(
                                f"Deleted customer_id: {customer_id}, project_id: {project_id}"
                            )
                        await function_db(
                            "delete_time_row", int(customer_id), int(project_id)
                        )
                        popup.close()

                    with ui.row().classes("justify-end"):
                        ui.button("Save", on_click=save_popup)
                        ui.button("Close", on_click=close_popup).props("flat")
                        ui.button("Delete", on_click=delete_popup)
            popup.open()

    def make_callback(customer_id, project_id):
        return lambda e: on_checkbox_change(e, e.value, customer_id, project_id)

    value_labels = []

    async def get_ui_data():
        date_range_str = date_input.value
        start_date, end_date = helpers.parse_date_range(date_range_str)
        if not start_date or not end_date:  # Fallback to today if not set
            today = datetime.now().strftime("%Y%m%d")
            start_date = end_date = today
        df = await function_db(
            "get_customer_ui_list", start_date=start_date, end_date=end_date
        )
        return df

    async def render_ui():
        value_labels.clear()
        df = await get_ui_data()

        container.clear()
        customers = df.groupby(["customer_id", "customer_name"])
        with container:
            with (
                ui.row()
                .classes("justify-between overflow-x-auto")
                .style("flex-wrap:nowrap; width:100%; max-width:1800px; margin:0 auto;")
            ):
                for (customer_id, customer_name), group in customers:
                    with (
                        ui.column()
                        .classes("items-start")
                        .style(
                            "flex:1 1 320px; min-width:320px; max-width:420px; margin:0 12px; box-sizing:border-box;"
                        )
                    ):
                        ui.label(str(customer_name)).classes("text-h6")
                        for _, project in group.iterrows():
                            with (
                                ui.row()
                                .classes("items-center w-full")
                                .style(
                                    "display: grid; grid-template-columns: 20px 1fr 100px; align-items: center; margin-bottom:2px; min-height:20px;"
                                )
                            ):
                                sql_query = f"select * from time where customer_id = {customer_id} and project_id = {project['project_id']} and end_time is null"
                                df_counts = await query_db(sql_query)
                                initial_state = True if len(df_counts) > 0 else False

                                ui.checkbox(
                                    on_change=make_callback(
                                        project["customer_id"], project["project_id"]
                                    ),
                                    value=initial_state,
                                )
                                ui.label(str(project["project_name"])).classes(
                                    "ml-2 truncate"
                                )
                                time_string = (
                                    f"{project['total_time']} h"
                                    if "time" in radio_display_selection.value.lower()
                                    else f"{project['user_bonus']} SEK"
                                )
                                value_label = (
                                    ui.label(f"{time_string}")
                                    .classes(
                                        "text-grey text-right whitespace-nowrap w-full"
                                    )
                                    .style("max-width:100px; overflow-x:auto;")
                                )
                                value_labels.append(
                                    (value_label, customer_id, project["project_id"])
                                )

    async def update_ui():
        df = await get_ui_data()
        # Build a lookup for (customer_id, project_id) to row
        df_lookup = {
            (row["customer_id"], row["project_id"]): row for _, row in df.iterrows()
        }
        for value_label, customer_id, project_id in value_labels:
            row = df_lookup.get((customer_id, project_id))
            if row is not None:
                time_string = (
                    f"{row['total_time']} h"
                    if "time" in radio_display_selection.value.lower()
                    else f"{row['user_bonus']} SEK"
                )
                value_label.text = time_string

    # Initial render
    asyncio.run(render_ui())


def ui_add_data():
    global add_data_df
    asyncio.run(refresh_add_data())

    def date_input(label):
        with ui.input(label).props("readonly").classes(input_width) as date:
            with ui.menu().props("no-parent-event") as menu:
                with ui.date().bind_value(date):
                    with ui.row().classes("justify-end"):
                        ui.button("Close", on_click=menu.close).props("flat")
            with date.add_slot("append"):
                ui.icon("edit_calendar").on("click", menu.open).classes(
                    "cursor-pointer"
                )
        return date

    def make_input_row(fields):
        widgets = {}
        for field in fields:
            label = field["label"]
            if field.get("optional", True):
                label += " (optional)"

            if field["type"] == "input":
                widgets[field["name"]] = ui.input(label).classes(input_width)
            elif field["type"] == "number":
                widgets[field["name"]] = ui.number(label, min=0).classes(input_width)
            elif field["type"] == "date":
                widgets[field["name"]] = date_input(label)
            elif field["type"] == "select":
                widgets[field["name"]] = ui.select(
                    field["options"], label=label
                ).classes(input_width)
        return widgets

    def autofill_widgets(widgets, row, field_map):
        for widget_name, col_name in field_map.items():
            widgets[widget_name].value = row.get(col_name, "")
            widgets[widget_name].update()

    def clear_widgets(widgets):
        for widget in widgets.values():
            widget.value = ""
            widget.update()

    def check_input(widgets, required_fields) -> bool:
        is_ok = True
        for field in required_fields:
            if not widgets[field].value:
                ui.notify(
                    f"{field.replace('_', ' ').title()} is required!",
                    color="negative",
                    close_button="OK",
                )
                is_ok = False
        return is_ok

    def print_success(
        table: str, main_param: str, action_type: str, widgets: dict = None
    ):
        ui.notify(
            f"{table} {main_param} {action_type}!",
            color="positive",
            close_button="OK",
        )
        if debug and widgets:
            print_msg = ""
            for field in widgets:
                print_msg += f"{field}: {widgets[field].value}, "
            print_msg = print_msg.rstrip(", ")
            ui.notify(print_msg)

    def filter_df(df, filters):
        mask = None
        for col, val in filters.items():
            if mask is None:
                mask = df[col] == val
            else:
                mask &= df[col] == val
        return df.loc[mask] if mask is not None else df

    # --- Modular Tab Panel Builder ---
    def add_save_button(save_data, fields, widgets):
        async def on_save():
            required_fields = [
                f["name"] for f in fields if not f.get("optional", False)
            ]
            if not check_input(widgets, required_fields):
                return
            kwargs = {f["name"]: widgets[f["name"]].value for f in fields}
            await function_db(save_data.function, **kwargs)
            print_success(
                save_data.main_action,
                widgets[save_data.main_param].value,
                save_data.secondary_action,
                widgets=widgets,
            )
            await refresh_add_data()

        ui.button(save_data.button_name, on_click=on_save).classes("mt-2")

    def build_customer_tab_panel(tab_type):
        container = tab_customer_containers.get(tab_type)
        if container is None:
            container = ui.element()
            tab_customer_containers[tab_type] = container
        container.clear()
        with container:
            if tab_type == "Add":
                fields = [
                    {
                        "name": "customer_name",
                        "label": "Name",
                        "type": "input",
                        "optional": False,
                    },
                    {
                        "name": "wage",
                        "label": "Wage",
                        "type": "number",
                        "optional": False,
                    },
                    {
                        "name": "start_date",
                        "label": "Start Date",
                        "type": "date",
                        "optional": False,
                    },
                    {
                        "name": "org_url",
                        "label": "DevOps Org. URL",
                        "type": "input",
                        "optional": True,
                    },
                    {
                        "name": "pat_token",
                        "label": "DevOps PAT",
                        "type": "input",
                        "optional": True,
                    },
                ]
                widgets = make_input_row(fields)
                save_data = SaveData(
                    function="insert_customer",
                    main_action="Customer",
                    main_param="customer_name",
                    secondary_action="added",
                    button_name="Add",
                )
                add_save_button(save_data, fields, widgets)
            elif tab_type == "Update":
                customer_data = (
                    add_data_df[add_data_df["c_current"] == 1]["customer_name"]
                    .unique()
                    .tolist()
                )
                fields = [
                    {
                        "name": "customer_name",
                        "label": "Name",
                        "type": "select",
                        "options": customer_data,
                        "optional": False,
                    },
                    {
                        "name": "new_customer_name",
                        "label": "New Name",
                        "type": "input",
                        "optional": False,
                    },
                    {
                        "name": "org_url",
                        "label": "DevOps Org. URL",
                        "type": "input",
                        "optional": True,
                    },
                    {
                        "name": "pat_token",
                        "label": "DevOps PAT",
                        "type": "input",
                        "optional": True,
                    },
                ]
                widgets = make_input_row(fields)
                save_data = SaveData(
                    function="update_customer",
                    main_action="Customer",
                    main_param="customer_name",
                    secondary_action="updated",
                    button_name="Update",
                )

                def on_name_change(e):
                    filtered = filter_df(
                        add_data_df,
                        {
                            "c_current": 1,
                            "customer_name": widgets["customer_name"].value,
                        },
                    )
                    if filtered.empty:
                        clear_widgets(
                            {k: v for k, v in widgets.items() if k != "customer_name"}
                        )
                        return
                    row = filtered.iloc[0]
                    autofill_widgets(
                        widgets,
                        row,
                        {
                            "new_customer_name": "customer_name",
                            "org_url": "org_url",
                            "pat_token": "pat_token",
                        },
                    )

                widgets["customer_name"].on("update:model-value", on_name_change)

                add_save_button(save_data, fields, widgets)
            elif tab_type == "Disable":
                customer_data = (
                    add_data_df[add_data_df["c_current"] == 1]["customer_name"]
                    .unique()
                    .tolist()
                )
                fields = [
                    {
                        "name": "customer_name",
                        "label": "Name",
                        "type": "select",
                        "options": customer_data,
                        "optional": False,
                    },
                ]
                save_data = SaveData(
                    function="disable_customer",
                    main_action="Customer",
                    main_param="customer_name",
                    secondary_action="disabled",
                    button_name="Disable",
                )
                widgets = make_input_row(fields)
                add_save_button(save_data, fields, widgets)
            elif tab_type == "Reenable":
                # Only show customer_name where c_current == 0 and NOT present in any row where c_current == 1
                all_current_names = set(
                    add_data_df[add_data_df["c_current"] == 1]["customer_name"]
                    .unique()
                    .tolist()
                )
                candidate_names = set(
                    add_data_df[add_data_df["c_current"] == 0]["customer_name"]
                    .unique()
                    .tolist()
                )
                reenable_names = sorted(list(candidate_names - all_current_names))
                fields = [
                    {
                        "name": "customer_name",
                        "label": "Name",
                        "type": "select",
                        "options": reenable_names,
                        "optional": False,
                    },
                ]
                save_data = SaveData(
                    function="enable_customer",
                    main_action="Customer",
                    main_param="customer_name",
                    secondary_action="enabled",
                    button_name="Re-enable",
                )
                widgets = make_input_row(fields)
                add_save_button(save_data, fields, widgets)

    def build_project_tab_panel(tab_type):
        container = tab_project_containers.get(tab_type)
        if container is None:
            container = ui.element()
            tab_project_containers[tab_type] = container
        container.clear()
        with container:
            active_data = add_data_df[add_data_df["c_current"] == 1]
            if tab_type == "Add":
                customer_data = active_data["customer_name"].unique().tolist()
                fields = [
                    {
                        "name": "customer_name",
                        "label": "Customer",
                        "type": "select",
                        "options": customer_data,
                        "optional": False,
                    },
                    {
                        "name": "project_name",
                        "label": "Project Name",
                        "type": "input",
                        "optional": False,
                    },
                    {
                        "name": "git_id",
                        "label": "Git ID",
                        "type": "number",
                        "optional": True,
                    },
                ]
                widgets = make_input_row(fields)
                save_data = SaveData(
                    function="add_project",
                    main_action="Project",
                    main_param="project_name",
                    secondary_action="added",
                    button_name="Add",
                )
                add_save_button(save_data, fields, widgets)
            elif tab_type == "Update":
                customer_data = active_data["customer_name"].unique().tolist()
                fields = [
                    {
                        "name": "customer_name",
                        "label": "Customer",
                        "type": "select",
                        "options": customer_data,
                        "optional": False,
                    },
                    {
                        "name": "project_name",
                        "label": "Project",
                        "type": "select",
                        "options": [],
                        "optional": False,
                    },
                    {
                        "name": "new_project_name",
                        "label": "New Project Name",
                        "type": "input",
                        "optional": False,
                    },
                    {
                        "name": "new_git_id",
                        "label": "New Git ID",
                        "type": "number",
                        "optional": True,
                    },
                ]
                widgets = make_input_row(fields)
                save_data = SaveData(
                    function="add_project",
                    main_action="Project",
                    main_param="project_name",
                    secondary_action="added",
                    button_name="Add",
                )

                def on_customer_change(e):
                    filtered = (
                        active_data[
                            active_data["customer_name"]
                            == widgets["customer_name"].value
                        ]["project_name"]
                        .unique()
                        .tolist()
                    )
                    widgets["project_name"].options = filtered
                    widgets["project_name"].update()

                widgets["customer_name"].on("update:model-value", on_customer_change)

                def on_project_change(e):
                    filtered = active_data.loc[
                        (active_data["customer_name"] == widgets["customer_name"].value)
                        & (active_data["project_name"] == widgets["project_name"].value)
                    ]
                    if filtered.empty:
                        clear_widgets(
                            {
                                k: v
                                for k, v in widgets.items()
                                if k not in ["customer_name", "project_name"]
                            }
                        )
                        return
                    row = filtered.iloc[0]
                    autofill_widgets(
                        widgets,
                        row,
                        {"new_project_name": "project_name", "new_git_id": "git_id"},
                    )

                widgets["project_name"].on("update:model-value", on_project_change)

                add_save_button(save_data, fields, widgets)
            elif tab_type == "Disable":
                customer_data = active_data["customer_name"].unique().tolist()
                fields = [
                    {
                        "name": "customer_name",
                        "label": "Customer",
                        "type": "select",
                        "options": customer_data,
                        "optional": False,
                    },
                    {
                        "name": "project_name",
                        "label": "Project",
                        "type": "select",
                        "options": [],
                        "optional": False,
                    },
                ]
                widgets = make_input_row(fields)
                save_data = SaveData(
                    function="disable_project",
                    main_action="Project",
                    main_param="project_name",
                    secondary_action="disabled",
                    button_name="Disable",
                )

                def on_customer_change(e):
                    filtered = (
                        active_data[
                            (
                                active_data["customer_name"]
                                == widgets["customer_name"].value
                            )
                            & (active_data["p_current"] == 1)
                        ]["project_name"]
                        .unique()
                        .tolist()
                    )
                    widgets["project_name"].options = filtered
                    widgets["project_name"].update()

                widgets["customer_name"].on("update:model-value", on_customer_change)
                add_save_button(save_data, fields, widgets)
            elif tab_type == "Reenable":
                customer_data = active_data["customer_name"].unique().tolist()
                fields = [
                    {
                        "name": "customer_name",
                        "label": "Customer",
                        "type": "select",
                        "options": customer_data,
                        "optional": False,
                    },
                    {
                        "name": "project_name",
                        "label": "Project",
                        "type": "select",
                        "options": [],
                        "optional": False,
                    },
                ]
                widgets = make_input_row(fields)
                save_data = SaveData(
                    function="enable_project",
                    main_action="Project",
                    main_param="project_name",
                    secondary_action="enabled",
                    button_name="Re-Enable",
                )

                def on_customer_change(e):
                    filtered = (
                        add_data_df[
                            (
                                add_data_df["customer_name"]
                                == widgets["customer_name"].value
                            )
                            & (add_data_df["p_current"] == 0)
                        ]["project_name"]
                        .unique()
                        .tolist()
                    )
                    widgets["project_name"].options = filtered
                    widgets["project_name"].update()

                widgets["customer_name"].on("update:model-value", on_customer_change)
                add_save_button(save_data, fields, widgets)

    def build_bonus_tab_panel(tab_type):
        container = tab_bonus_containers.get(tab_type)
        if container is None:
            container = ui.element()
            tab_bonus_containers[tab_type] = container
        container.clear()
        with container:
            if tab_type == "Add":
                fields = [
                    {
                        "name": "bonus_percent",
                        "label": "Bonus Percentage (%)",
                        "type": "number",
                        "optional": False,
                    },
                    {
                        "name": "start_date",
                        "label": "Start Date",
                        "type": "date",
                        "optional": False,
                    },
                ]
                widgets = make_input_row(fields)
                save_data = SaveData(
                    function="insert_bonus",
                    main_action="Bonus",
                    main_param="bonus_percent",
                    secondary_action="added",
                    button_name="Add",
                )
                add_save_button(save_data, fields, widgets)

    input_width = "w-64"

    with ui.splitter(value=30).classes("w-full h-full") as splitter:
        with splitter.before:
            with ui.tabs().props("vertical").classes("w-full") as main_tabs:
                tab_customers = ui.tab("Customers", icon="business")
                tab_projects = ui.tab("Projects", icon="assignment")
                tab_bonuses = ui.tab("Bonuses", icon="attach_money")
        with splitter.after:
            with (
                ui.tab_panels(main_tabs, value=tab_customers)
                .props("vertical")
                .classes("w-full h-full")
            ):
                tab_customer_containers = {}
                tab_project_containers = {}
                tab_bonus_containers = {}

                async def on_customer_tab_change(e):
                    tab_type = e.args
                    await refresh_add_data()
                    build_customer_tab_panel(tab_type)

                async def on_project_tab_change(e):
                    tab_type = e.args
                    await refresh_add_data()
                    build_project_tab_panel(tab_type)

                async def on_bonus_tab_change(e):
                    tab_type = e.args
                    await refresh_add_data()
                    build_bonus_tab_panel(tab_type)

                # Customers
                with ui.tab_panel(tab_customers):
                    with ui.tabs().classes("mb-2") as customer_tabs:
                        tab_add = ui.tab("Add")
                        tab_update = ui.tab("Update")
                        tab_disable = ui.tab("Disable")
                        tab_reenable = ui.tab("Reenable")
                    with ui.tab_panels(customer_tabs, value=tab_add):
                        with ui.tab_panel(tab_add):
                            build_customer_tab_panel("Add")
                        with ui.tab_panel(tab_update):
                            build_customer_tab_panel("Update")
                        with ui.tab_panel(tab_disable):
                            build_customer_tab_panel("Disable")
                        with ui.tab_panel(tab_reenable):
                            build_customer_tab_panel("Reenable")
                # Projects
                with ui.tab_panel(tab_projects):
                    with ui.tabs().classes("mb-2") as project_tabs:
                        tab_add = ui.tab("Add")
                        tab_update = ui.tab("Update")
                        tab_disable = ui.tab("Disable")
                        tab_reenable = ui.tab("Reenable")
                    with ui.tab_panels(project_tabs, value=tab_add):
                        with ui.tab_panel(tab_add):
                            build_project_tab_panel("Add")
                        with ui.tab_panel(tab_update):
                            build_project_tab_panel("Update")
                        with ui.tab_panel(tab_disable):
                            build_project_tab_panel("Disable")
                        with ui.tab_panel(tab_reenable):
                            build_project_tab_panel("Reenable")

                # Bonuses
                with ui.tab_panel(tab_bonuses):
                    with ui.tabs().classes("mb-2") as bonus_tabs:
                        tab_add = ui.tab("Add")
                        # tab_update = ui.tab("Update")
                        # tab_disable = ui.tab("Disable")
                        # tab_reenable = ui.tab("Reenable")
                    with ui.tab_panels(bonus_tabs, value=tab_add):
                        with ui.tab_panel(tab_add):
                            build_bonus_tab_panel("Add")
                        with ui.tab_panel(tab_update):
                            build_bonus_tab_panel("Update")
                        with ui.tab_panel(tab_disable):
                            build_bonus_tab_panel("Disable")
                        with ui.tab_panel(tab_reenable):
                            build_bonus_tab_panel("Reenable")

            customer_tabs.on("update:model-value", on_customer_tab_change)
            project_tabs.on("update:model-value", on_project_tab_change)
            bonus_tabs.on("update:model-value", on_bonus_tab_change)


def ui_edit_settings():
    ui.label("UI Edits")


def ui_query_editor():
    ui.label("Query Editors")

    editor = ui.codemirror(
        "select * from time\norder by time_id desc\nlimit 50",
        language="SQLite",
        theme="dracula",
    ).classes("h-48 w-full")
    grid_box = ui.aggrid(
        {
            "columnDefs": [{"field": ""}],
            "rowData": [],
        },
        theme="alpine-dark",
    ).classes("h-96 w-full")

    async def run_code():
        query = editor.value
        try:
            df = await query_db(query)
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
    ui.label("Log")


def setup_ui():
    dark = ui.dark_mode()
    dark.enable()

    with ui.tabs().classes("w-full") as tabs:
        tab_time = ui.tab("Time Tracking")
        tab_data_input = ui.tab("Data Input")
        tab_ui_edits = ui.tab("UI Edits")
        tab_query_editors = ui.tab("Query Editors")
        tab_log = ui.tab("Log")
    with ui.tab_panels(tabs, value=tab_time).classes("w-full"):
        with ui.tab_panel(tab_time):
            ui_time_tracking()
        with ui.tab_panel(tab_data_input):
            ui_add_data()
        with ui.tab_panel(tab_ui_edits):
            ui_edit_settings()
        with ui.tab_panel(tab_query_editors):
            ui_query_editor()
        with ui.tab_panel(tab_log):
            ui_log()

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
    #     elif e.key.arrow_right:
    #         ui.notify("going right")
    #     elif e.key.arrow_up:
    #         ui.notify("going up")
    #     elif e.key.arrow_down:
    #         ui.notify("going down")
    1


if __name__ in {"__main__", "__mp_main__"}:
    main()
    setup_db("data_dpg_copy.db")

    ui.add_head_html("""
    <script>
    document.addEventListener('keydown', function(e) {
        if (e.key === 'F5') {
            e.preventDefault();
        }
    });
    </script>
    """)

    asyncio.run(setup_devops())
    setup_ui()
    ui.run()
