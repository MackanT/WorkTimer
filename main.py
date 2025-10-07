from nicegui import events, ui
from nicegui.events import KeyEventArguments
import pandas as pd
import helpers
import asyncio
from database_new import Database
from devops_new import DevOpsManager
from datetime import datetime
from dataclasses import dataclass
from textwrap import dedent
import threading
import tempfile
import os
import yaml
import logging

debug = True


## Globals ##
add_data_df = None
query_df = None
devops_manager = None
devops_df = None
devops_long_df = None

MAIN_DB = "data_dpg_copy.db"
CONFIG_FOLDER = "config"

## Logging Setup ##
LOGFORMAT = "%(asctime)s | %(levelname)-8s | %(name).35s :: %(message)s"
formatter = logging.Formatter(fmt=LOGFORMAT, datefmt="%Y-%m-%d %H:%M:%S")
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger = logging.getLogger("WorkTimer")
logger.setLevel(logging.DEBUG if debug else logging.INFO)
logger.addHandler(handler)


@dataclass
class SaveData:
    function: str
    main_action: str
    main_param: str
    secondary_action: str
    button_name: str = "Save"


@dataclass
class TableColumn:
    editable: bool = False
    pk: bool = False
    type: str = "str"


@dataclass
class DevOpsTag:
    name: str = ""
    icon: str = "bookmark"
    color: str = "green"


async def refresh_add_data():
    global add_data_df
    df = await function_db("get_data_input_list")
    add_data_df = df


async def refresh_query_data():
    global query_df
    df = await function_db("get_query_list")
    query_df = df


## Config Setup ##
def setup_config():
    global config_ui, config_devops_ui, config_data, DEVOPS_TAGS, TABLE_IDS

    with open(f"{CONFIG_FOLDER}/config_ui.yml") as f:
        fields = yaml.safe_load(f)
    config_ui = fields
    with open(f"{CONFIG_FOLDER}/config_devops_ui.yml") as f:
        fields = yaml.safe_load(f)
    config_devops_ui = fields
    with open(f"{CONFIG_FOLDER}/config_data.yml") as f:
        fields = yaml.safe_load(f)
    config_data = fields

    DEVOPS_TAGS = []
    for f in config_data["devops_tags"]:
        DEVOPS_TAGS.append(DevOpsTag(**f))
    TABLE_IDS = {}
    for table_name, columns in config_data["table_ids"].items():
        TABLE_IDS[table_name] = {
            col_name: TableColumn(**(columns[col_name] or {})) for col_name in columns
        }


## DB SETUP ##
def setup_db(db_file: str):
    Database(db_file).initialize_db()


async def function_db(func_name: str, *args, **kwargs):
    func = getattr(Database.db, func_name)
    return await asyncio.to_thread(func, *args, **kwargs)


async def query_db(query: str):
    return await asyncio.to_thread(Database.db.smart_query, query)


async def update_devops():
    global devops_df
    if not devops_manager:
        log_msg("WARNING", "No DevOps connections available")
        return None
    log_msg("INFO", "Getting latest devops data")
    status, devops_df = devops_manager.get_epics_feature_df()
    if status:
        await function_db("update_devops_data", df=devops_df)
    else:
        log_msg("ERROR", f"Error when updating the devops data: {devops_df}")


async def get_devops_df():
    global devops_df, devops_long_df
    df = await query_db("select * from devops")
    devops_df = df if not df.empty else None
    if devops_df.empty:
        log_msg("WARNING", "DevOps dataframe is empty")
    else:
        devops_long_df = get_devops_long_df(devops_df)
        log_msg(
            "INFO", f"DevOps dataframe loaded with {len(devops_df)} rows"
        )  # TODO add some date when it was last collected


def get_devops_long_df(devops_df):
    if devops_df is None or devops_df.empty:
        return None
    records = []
    for _, row in devops_df.iterrows():
        # Epic
        if pd.notna(row.get("epic_id")):
            records.append(
                {
                    "customer_name": row["customer_name"],
                    "type": "Epic",
                    "id": int(row["epic_id"]),
                    "title": row["epic_title"],
                    "state": row["epic_state"],
                    "name": f"Epic: {int(row['epic_id'])} - {row['epic_title']}",
                    "parent_id": None,
                }
            )
        # Feature
        if pd.notna(row.get("feature_id")):
            records.append(
                {
                    "customer_name": row["customer_name"],
                    "type": "Feature",
                    "id": int(row["feature_id"]),
                    "title": row["feature_title"],
                    "state": row["feature_state"],
                    "name": f"Feature: {int(row['feature_id'])} - {row['feature_title']}",
                    "parent_id": int(row["epic_id"])
                    if pd.notna(row.get("epic_id"))
                    else None,
                }
            )
        # User Story
        if pd.notna(row.get("user_story_id")):
            records.append(
                {
                    "customer_name": row["customer_name"],
                    "type": "User Story",
                    "id": int(row["user_story_id"]),
                    "title": row["user_story_title"],
                    "state": row["user_story_state"],
                    "name": f"User Story: {int(row['user_story_id'])} - {row['user_story_title']}",
                    "parent_id": int(row["feature_id"])
                    if pd.notna(row.get("feature_id"))
                    else None,
                }
            )
    long_df = pd.DataFrame(records)
    long_df = long_df[long_df["state"].isin(["New", "Active"])].drop_duplicates()
    return long_df


## DEVOPS SETUP ##
async def setup_devops():
    global devops_manager
    df = await query_db(
        "select distinct customer_name, pat_token, org_url from customers where pat_token is not null and pat_token is not '' and org_url is not null and org_url is not '' and is_current = 1"
    )
    devops_manager = DevOpsManager(df)


def devops_helper(func_name: str, customer_name: str, *args, **kwargs):
    if not devops_manager:
        log_msg("WARNING", "No DevOps connections available")
        return None
    msg = None
    if func_name == "save_comment":
        status, msg = devops_manager.save_comment(
            customer_name=customer_name,
            comment=kwargs.get("comment"),
            git_id=int(kwargs.get("git_id")),
        )
    elif func_name == "get_workitem_level":
        git_id_raw = kwargs.get("git_id")
        status, msg = devops_manager.get_workitem_level(
            customer_name=customer_name,
            work_item_id=int(git_id_raw) if str(git_id_raw).isnumeric() else None,
            level=kwargs.get("level"),
        )
    if not status:
        log_msg("ERROR", msg)
    return status, msg


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
        log_msg("DEBUG", f"Date picker selected: {date_input.value}")
        selected_time.value = "Custom"
        asyncio.create_task(update_ui())

    def on_radio_time_change(e):
        log_msg("DEBUG", f"Radio Date selected: {selected_time.value}")
        date_input.value = helpers.get_range_for(selected_time.value)
        asyncio.create_task(update_ui())

    def on_radio_type_change(e):
        log_msg("DEBUG", f"Radio Type selected: {radio_display_selection.value}")
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
            log_msg(
                "DEBUG",
                f"Checkbox status: {checked}, customer_id: {customer_id}, project_id: {project_id}",
            )
            run_async_task(
                lambda: asyncio.run(
                    function_db("insert_time_row", int(customer_id), int(project_id))
                )
            )

        else:
            # Show a centered popup/modal with input and three buttons
            checkbox = event.sender
            with ui.dialog().props("persistent") as popup:
                with ui.card().classes("w-112"):
                    sql_query = f"""
                    select distinct t.customer_name, t.project_name, p.git_id from time t
                    left join projects p on p.project_id = t.project_id
                    where t.customer_id = {customer_id}
                    and t.project_id = {project_id}
                    """
                    df = await query_db(sql_query)
                    c_name = df.iloc[0]["customer_name"] if not df.empty else "Unknown"
                    p_name = df.iloc[0]["project_name"] if not df.empty else "Unknown"
                    git_id = df.iloc[0]["git_id"] if not df.empty else 0
                    has_git_id = git_id is not None and git_id > 0

                    ui.label(f"{p_name} - {c_name}").classes("text-h6 w-full")

                    id_options = devops_long_df[
                        (devops_long_df["customer_name"] == c_name)
                    ][["name", "id"]].dropna()

                    id_input = ui.select(
                        id_options["name"].tolist(), with_input=True, label="DevOps-ID"
                    ).classes("w-full -mb-2")
                    if has_git_id:
                        id_input.value = id_options[id_options["id"] == git_id][
                            "name"
                        ].iloc[0]

                    with ui.row().classes("w-full items-center justify-between -mt-2"):

                        def toggle_switch():
                            id_checkbox.value = not id_checkbox.value
                            id_checkbox.update()

                        ui.label("Store to DevOps").on("click", toggle_switch).classes(
                            "cursor-pointer"
                        )
                        id_checkbox = ui.switch(value=has_git_id).props("dense")
                    comment_input = ui.textarea(
                        label="Comment", placeholder="What work was done?"
                    ).classes("w-full -mt-2")

                    def close_popup():
                        popup.close()
                        checkbox.value = True

                    async def save_popup():
                        git_id_str = id_input.value
                        git_id = None
                        if git_id_str and isinstance(git_id_str, str):
                            ind_1 = git_id_str.find(":")
                            ind_2 = git_id_str.find(" - ")
                            if ind_1 != -1 and ind_2 != -1 and ind_2 > ind_1:
                                try:
                                    git_id = int(git_id_str[ind_1 + 1 : ind_2].strip())
                                except ValueError:
                                    git_id = None

                        log_msg(
                            "DEBUG",
                            f"Saved: {git_id}, {id_checkbox.value}, {comment_input.value}, customer_id: {customer_id}, project_id: {project_id}",
                        )

                        run_async_task(
                            lambda: asyncio.run(
                                function_db(
                                    "insert_time_row",
                                    int(customer_id),
                                    int(project_id),
                                    git_id=git_id,
                                    comment=comment_input.value,
                                )
                            )
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
                                    )
                                else:
                                    ui.notify(
                                        "Comment stored successfully",
                                        color="positive",
                                    )
                        popup.close()

                    async def delete_popup():
                        log_msg(
                            "DEBUG",
                            f"Deleted customer_id: {customer_id}, project_id: {project_id}",
                        )
                        await function_db(
                            "delete_time_row", int(customer_id), int(project_id)
                        )
                        ui.notify("Entry deleted", color="negative")
                        popup.close()

                    with ui.row().classes("justify-end gap-2"):
                        btn_classes = "w-28"
                        ui.button("Save", on_click=save_popup).classes(btn_classes)
                        ui.button("Delete", on_click=delete_popup).props(
                            "color=negative"
                        ).classes(f"q-btn--warning {btn_classes}")
                        ui.button("Close", on_click=close_popup).props("flat").classes(
                            btn_classes
                        )
            popup.open()

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
        df = await function_db(
            "get_customer_ui_list", start_date=start_date, end_date=end_date
        )
        return df

    global render_ui

    async def render_ui():
        value_labels.clear()
        customer_total_labels.clear()
        df = await get_ui_data()

        container.clear()

        customers = df.groupby(["customer_id", "customer_name"])
        with container:
            with (
                ui.row()
                .classes("px-4 justify-between overflow-x-auto")
                .style("flex-wrap:nowrap; width:100%; max-width:1800px; margin:0 auto;")
            ):
                for (customer_id, customer_name), group in customers:
                    with ui.card().classes("w-full max-w-2xl mx-auto mx-6 my-4 p-6"):
                        with (
                            ui.column()
                            .classes("items-start")
                            .style(
                                "flex:1 1 320px; min-width:320px; max-width:420px; margin:0 12px; box-sizing:border-box;"
                            )
                        ):
                            total_string = (
                                f"{df[df['customer_id'] == customer_id]['total_time'].sum():.2f} h"
                                if "time" in radio_display_selection.value.lower()
                                else f"{df[df['customer_id'] == customer_id]['user_bonus'].sum():.2f} SEK"
                            )
                            with (
                                ui.row()
                                .classes("w-full justify-between")
                                .style("display:flex; align-items:center;")
                            ):
                                ui.label(str(customer_name)).classes(
                                    "text-lg text-right"
                                )
                                label_total = ui.label(total_string).classes(
                                    "text-base text-grey text-right"
                                )
                                customer_total_labels.append((label_total, customer_id))
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
                                    initial_state = (
                                        True if len(df_counts) > 0 else False
                                    )

                                    ui.checkbox(
                                        on_change=make_callback(
                                            project["customer_id"],
                                            project["project_id"],
                                        ),
                                        value=initial_state,
                                    )
                                    ui.label(str(project["project_name"])).classes(
                                        "ml-2 truncate"
                                    )
                                    total_string = (
                                        f"{project['total_time']} h"
                                        if "time"
                                        in radio_display_selection.value.lower()
                                        else f"{project['user_bonus']} SEK"
                                    )
                                    value_label = (
                                        ui.label(f"{total_string}")
                                        .classes(
                                            "text-grey text-right whitespace-nowrap w-full"
                                        )
                                        .style("max-width:100px; overflow-x:auto;")
                                    )
                                    value_labels.append(
                                        (
                                            value_label,
                                            customer_id,
                                            project["project_id"],
                                        )
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
    global add_data_df
    asyncio.run(refresh_add_data())

    # --- Modular Tab Panel Builder ---
    def add_save_button(save_data, fields, widgets):
        async def on_save():
            required_fields = [
                f["name"] for f in fields if not f.get("optional", False)
            ]
            if not helpers.check_input(widgets, required_fields):
                return
            kwargs = {f["name"]: widgets[f["name"]].value for f in fields}
            await function_db(save_data.function, **kwargs)
            msg_1, msg_2 = helpers.print_success(
                save_data.main_action,
                widgets[save_data.main_param].value,
                save_data.secondary_action,
                widgets=widgets,
            )
            log_msg("INFO", msg_1)
            log_msg("INFO", msg_2)
            await refresh_add_data()

        ui.button(save_data.button_name, on_click=on_save).classes("mt-2")

    def build_customer_tab_panel(tab_type, container_dict):
        container = container_dict.get(tab_type)
        if container is None:
            container = ui.element()
            container_dict[tab_type] = container
        container.clear()

        fields = config_ui["customer"][tab_type.lower()]["fields"]
        action = config_ui["customer"][tab_type.lower()]["action"]

        active_data = helpers.filter_df(add_data_df, {"c_current": 1})

        with container:
            if tab_type == "Add":
                helpers.assign_dynamic_options(fields, data_sources={"date": None})
                widgets = helpers.make_input_row(fields)
                save_data = SaveData(**action)
                add_save_button(save_data, fields, widgets)
            elif tab_type == "Update":
                customer_names = helpers.get_unique_list(active_data, "customer_name")

                org_urls = {}
                pat_tokens = {}
                new_customer_names = {}

                for customer in customer_names:
                    filtered = helpers.filter_df(
                        add_data_df, {"customer_name": customer}
                    )
                    org_urls[customer] = helpers.get_unique_list(filtered, "org_url")
                    pat_tokens[customer] = helpers.get_unique_list(
                        filtered, "pat_token"
                    )
                    new_customer_names[customer] = [customer]

                helpers.assign_dynamic_options(
                    fields,
                    data_sources={
                        "customer_data": customer_names,
                        "new_customer_name": new_customer_names,
                        "org_url": org_urls,
                        "pat_token": pat_tokens,
                    },
                )

                widgets = helpers.make_input_row(fields)
                save_data = SaveData(**action)
                add_save_button(save_data, fields, widgets)
            elif tab_type == "Disable":
                customer_names = helpers.get_unique_list(active_data, "customer_name")
                helpers.assign_dynamic_options(
                    fields, data_sources={"customer_data": customer_names}
                )
                save_data = SaveData(**action)
                widgets = helpers.make_input_row(fields)
                add_save_button(save_data, fields, widgets)
            elif tab_type == "Reenable":
                # Only show customer_name where c_current == 0 and NOT present in any row where c_current == 1
                customer_names = helpers.get_unique_list(active_data, "customer_name")
                candidate_names = helpers.filter_df(
                    add_data_df,
                    {"c_current": 0},
                    return_as="distinct_list",
                    column="customer_name",
                )
                reenable_names = sorted(
                    list(set(candidate_names) - set(customer_names))
                )
                helpers.assign_dynamic_options(
                    fields, data_sources={"customer_data": reenable_names}
                )
                save_data = SaveData(**action)
                widgets = helpers.make_input_row(fields)
                add_save_button(save_data, fields, widgets)

    def build_project_tab_panel(tab_type, container_dict):
        container = container_dict.get(tab_type)
        if container is None:
            container = ui.element()
            container_dict[tab_type] = container
        container.clear()

        fields = config_ui["project"][tab_type.lower()]["fields"]
        action = config_ui["project"][tab_type.lower()]["action"]

        active_data = helpers.filter_df(
            add_data_df,
            {"c_current": 1},
        )
        active_customer_names = helpers.get_unique_list(active_data, "customer_name")

        with container:
            if tab_type == "Add":
                helpers.assign_dynamic_options(
                    fields, data_sources={"customer_data": active_customer_names}
                )
                widgets = helpers.make_input_row(fields)
                save_data = SaveData(**action)
                add_save_button(save_data, fields, widgets)
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

                helpers.assign_dynamic_options(
                    fields,
                    data_sources={
                        "customer_data": active_customer_names,
                        "project_names": project_names,
                        "new_project_name": new_project_name,
                        "new_git_id": new_git_id,
                    },
                )
                widgets = helpers.make_input_row(fields)
                save_data = SaveData(**action)
                add_save_button(save_data, fields, widgets)
            elif tab_type == "Disable":
                project_names = {}
                for customer in active_customer_names:
                    filtered = helpers.filter_df(
                        active_data, {"customer_name": customer, "p_current": 1}
                    )
                    project_names[customer] = helpers.get_unique_list(
                        filtered, "project_name"
                    )

                helpers.assign_dynamic_options(
                    fields,
                    data_sources={
                        "customer_data": active_customer_names,
                        "project_names": project_names,
                    },
                )
                widgets = helpers.make_input_row(fields)
                save_data = SaveData(**action)
                add_save_button(save_data, fields, widgets)
            elif tab_type == "Reenable":
                project_names = {}
                for customer in active_customer_names:
                    filtered = helpers.filter_df(
                        active_data, {"customer_name": customer, "p_current": 0}
                    )
                    project_names[customer] = helpers.get_unique_list(
                        filtered, "project_name"
                    )

                helpers.assign_dynamic_options(
                    fields,
                    data_sources={
                        "customer_data": active_customer_names,
                        "project_names": project_names,
                    },
                )
                widgets = helpers.make_input_row(fields)
                save_data = SaveData(**action)
                add_save_button(save_data, fields, widgets)

    def build_bonus_tab_panel(tab_type, container_dict):
        container = container_dict.get(tab_type)
        if container is None:
            container = ui.element()
            container_dict[tab_type] = container
        container.clear()

        fields = config_ui["bonus"][tab_type.lower()]["fields"]
        action = config_ui["bonus"][tab_type.lower()]["action"]

        with container:
            if tab_type == "Add":
                widgets = helpers.make_input_row(fields)
                save_data = SaveData(**action)
                add_save_button(save_data, fields, widgets)

    def build_database_compare():
        def handle_upload(e: events.UploadEventArguments):
            ui.notify(f"File uploaded: {e.name}", color="positive")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
                tmp.write(e.content.read())
                uploaded_path = tmp.name

            sync_sql = Database.generate_sync_sql(MAIN_DB, uploaded_path)
            db_deltas.set_content(sync_sql)
            db_deltas.update()
            os.remove(uploaded_path)  # Clean up temp file

        with ui.card().classes("w-full max-w-2xl mx-auto my-0 p-4"):
            ui.label("Upload a .db file to compare with the main database.").classes(
                "text-h5 mb-0 dense"
            )
            ui.label(
                "Ensure you backup the original db-file before running the generated code on it!"
            ).classes("text-caption text-red mb-0 dense")
            ui.upload(on_upload=handle_upload).props("accept=.db").classes(
                "q-pa-xs q-ma-xs"
            )
            ui.separator().classes("my-4")
            ui.label("SQL to synchronize uploaded DB:").classes("text-subtitle1 mb-2")
            db_deltas = (
                ui.code("--temp location of sql-changes...", language="sql")
                .props("readonly")
                .classes("w-full min-w-0 h-96")
            )

    tab_list = {}
    vertical_tab_entries = [i for i in config_ui]
    function_map = {
        "build_customer_tab_panel": build_customer_tab_panel,
        "build_project_tab_panel": build_project_tab_panel,
        "build_bonus_tab_panel": build_bonus_tab_panel,
    }
    with ui.splitter(value=30).classes("w-full h-full") as splitter:
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
                    await refresh_add_data()
                    function(tab_type, container)

                for tab_dict in tab_list.values():
                    tab_names = [
                        i.capitalize()
                        for i in helpers.get_ui_elements(config_ui[tab_dict["name"]])
                    ]

                    with ui.tab_panel(tab_dict["tab"]):
                        with ui.tabs().classes("mb-2") as temp_tab:
                            for name in tab_names:
                                tab_dict["tab_list"].append(ui.tab(name))
                        with ui.tab_panels(temp_tab, value=tab_dict["tab_list"][0]):
                            for i, name in enumerate(tab_names):
                                helpers.make_tab_panel(
                                    tab_dict["tab_list"][i],
                                    f"{name} {tab_dict['name']}",
                                    lambda: function_map[tab_dict["build_function"]](
                                        name, tab_dict["tab_container"]
                                    ),
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

                    with ui.tab_panels(database_tabs, value=tab_add):
                        with ui.tab_panel(tab_add):
                            build_database_compare()


def ui_devops_settings_entrypoint():
    """Checks if the data needed for the DevOps settings UI is ready. If not, shows a loading UI and polls for data readiness.
    Once the data is ready, it calls the ui_devops_settings() function to render the actual settings UI.
    """
    global devops_settings_container
    if (
        "devops_settings_container" not in globals()
        or devops_settings_container is None
    ):
        devops_settings_container = ui.element()
    devops_settings_container.clear()

    # Show loading UI
    with devops_settings_container:
        with ui.card().classes("w-full max-w-2xl mx-auto my-8 p-4"):
            ui.label("Loading DevOps data...").classes("text-h5 mb-4")
            ui.skeleton().classes("w-full")

    called = {"done": False}

    async def check_data_ready():
        if not called["done"] and devops_df is not None and devops_long_df is not None:
            called["done"] = True
            devops_settings_container.clear()
            await ui_devops_settings()
            return False  # Stop timer
        return not called["done"]

    ui.timer(callback=check_data_ready, interval=0.5)


async def ui_devops_settings():
    customer_names = helpers.get_unique_list(devops_df, "customer_name")

    epic_names = {}
    for customer in customer_names:
        filtered = helpers.filter_df(
            devops_long_df, {"customer_name": customer, "type": "Epic"}
        )
        # Temporary storing id and name - will drop id later
        epic_names[customer] = [
            (row["name"], row["id"]) for _, row in filtered.iterrows()
        ]

    feature_names = {}
    for customer in customer_names:
        for epic_name, epic_id in epic_names[customer]:
            filtered = helpers.filter_df(
                devops_long_df, {"customer_name": customer, "parent_id": epic_id}
            )
            feature_names[epic_name] = helpers.get_unique_list(filtered, "name")

    # Drop id from epic_names, only need the names now
    for customer in epic_names:
        epic_names[customer] = [name for name, _ in epic_names[customer]]

    def add_user_story(widgets):
        wid = helpers.parse_widget_values(widgets)

        description = f"""
            **Source:** {wid["source"]}
            **Contact:** {wid["contact_person"]}
            **Received Date:** {wid["item_date"]}

            **Problem:**
            {wid["problem_description"]}

            **More Info:**
            {wid["more_info"]}

            **Solution:**
            {wid["solution"]}

            **Validation:**
            {wid["validation"]}

        """

        additional_fields = {
            "System.State": wid["state"],
            "System.Tags": ", ".join([t for t in wid["tags"]]),
            "Microsoft.VSTS.Common.Priority": int(wid["priority"]),
            "System.AssignedTo": wid["assigned_to"],
        }
        parent_id = int(helpers.extract_devops_id(wid["feature_name"]))

        success, message = devops_manager.create_user_story(
            customer_name=wid["customer_name"],
            title=wid["user_story_name"],
            description=dedent(description),
            additional_fields=additional_fields,
            markdown=wid["use_markdown"],
            parent=parent_id,
        )
        state = "INFO" if success else "ERROR"
        log_msg(
            state,
            message,
        )
        return success, message

    def add_save_button(save_data, fields, widgets):
        async def on_save():
            required_fields = [
                f["name"] for f in fields if not f.get("optional", False)
            ]
            if not helpers.check_input(widgets, required_fields):
                return

            func_name = save_data.function
            if func_name == "add_user_story":
                state, msg = add_user_story(widgets=widgets)
            else:
                log_msg("WARNING", f"Function {func_name} not implemented yet")

            col = "positive" if state else "negative"
            ui.notify(
                msg,
                color=col,
            )

        ui.button(save_data.button_name, on_click=on_save).classes("mt-2")

    def build_user_story_tab_panel(tab_type):
        container = tab_user_story_containers.get(tab_type)
        if container is None:
            container = ui.element()
            tab_user_story_containers[tab_type] = container
        container.clear()

        fields = config_devops_ui["devops_user_story"][tab_type.lower()]["fields"]
        columns = config_devops_ui["devops_user_story"][tab_type.lower()].get(
            "columns", []
        )
        action = config_devops_ui["devops_user_story"][tab_type.lower()]["action"]

        with container:
            if tab_type == "Add":
                helpers.assign_dynamic_options(
                    fields,
                    data_sources={
                        "customer_data": customer_names,
                        "epic_names": epic_names,
                        "feature_names": feature_names,
                        "devops_tags": DEVOPS_TAGS,
                    },
                )
                widgets = {}
                with ui.row().classes("gap-8 mb-4"):
                    for col_fields in columns:
                        with ui.column():
                            col_fields_objs = [
                                next(f for f in fields if f["name"] == fname)
                                for fname in col_fields
                                if any(f["name"] == fname for f in fields)
                            ]
                            col_widgets = helpers.make_input_row(col_fields_objs)
                            widgets.update(col_widgets)

                save_data = SaveData(**action)
                add_save_button(save_data, fields, widgets)

    with ui.splitter(value=30).classes("w-full h-full") as splitter:
        with splitter.before:
            with ui.tabs().props("vertical").classes("w-full") as main_tabs:
                tab_user_story = ui.tab("User Story", icon="business")
                # tab_feature = ui.tab("Feature", icon="assignment")
                # tab_epic = ui.tab("Epic", icon="attach_money")
        with splitter.after:
            with (
                ui.tab_panels(main_tabs, value=tab_user_story)
                .props("vertical")
                .classes("w-full h-full")
            ):
                tab_user_story_containers = {}

                async def on_user_story_tab_change(e):
                    tab_type = e.args
                    await refresh_add_data()
                    build_user_story_tab_panel(tab_type)

                # User Stories
                user_story_tab_names = [
                    i.capitalize() for i in config_devops_ui["devops_user_story"]
                ]
                user_story_tab_list = []
                with ui.tab_panel(tab_user_story):
                    with ui.tabs().classes("mb-2") as user_story_tabs:
                        for name in user_story_tab_names:
                            user_story_tab_list.append(ui.tab(name))
                    with ui.tab_panels(user_story_tabs, value=user_story_tab_list[0]):
                        for i, name in enumerate(user_story_tab_names):
                            helpers.make_tab_panel(
                                user_story_tab_list[i],
                                f"{name} User Story",
                                lambda: build_user_story_tab_panel(name),
                                width="4",
                            )


def ui_query_editor():
    asyncio.run(refresh_query_data())

    async def save_custom_query():
        query = editor.value
        try:
            await query_db(query)

            with ui.dialog() as popup:
                with ui.card().classes("w-64"):
                    name_input = ui.input("Query Name").classes("w-full")

                    def close_popup():
                        popup.close()

                    async def save_popup():
                        name = name_input.value.strip()
                        if not name:
                            ui.notify("Query name required", color="negative")
                            return
                        if name in query_df["query_name"].tolist():
                            ui.notify("Query name already exists", color="negative")
                            return
                        # Save to queries table
                        await function_db(
                            "execute_query",
                            "insert into queries (query_name, query_sql) values (?, ?)",
                            (name, query),
                        )
                        ui.notify(f"Query '{name}' saved!", color="positive")
                        popup.close()
                        await refresh_query_data()
                        render_query_buttons()

                    with ui.row().classes("justify-between items-center w-full"):
                        ui.button("Save", on_click=save_popup).classes("w-24")
                        ui.button("Cancel", on_click=close_popup).props("flat").classes(
                            "w-24"
                        )
            popup.open()
        except Exception as e:
            ui.notify("Query is invalid", color="negative")
            log_msg("ERROR", f"Error: {e}")

    async def update_custom_query():
        if len(query_df[query_df["is_default"] != 1]["query_name"]) <= 1:
            ui.notify("At least one custom query must exist", color="negative")
            return

        query = editor.value
        try:
            await query_db(query)

            with ui.dialog() as popup:
                with ui.card().classes("w-64"):
                    name_input = ui.select(
                        options=query_df[query_df["is_default"] != 1][
                            "query_name"
                        ].tolist(),
                        label="Existing Query",
                    ).classes("w-full")

                    def close_popup():
                        popup.close()

                    async def save_popup():
                        name = name_input.value.strip()
                        if not name:
                            ui.notify("Select a existing query", color="negative")
                            return
                        # Save to queries table
                        await function_db(
                            "execute_query",
                            "update queries set query_sql = ? where query_name = ?",
                            (query, name),
                        )
                        ui.notify(f"Query '{name}' updated!", color="positive")
                        popup.close()
                        await refresh_query_data()
                        render_query_buttons()

                    with ui.row().classes("justify-between items-center w-full"):
                        ui.button("Update", on_click=save_popup).classes("w-24")
                        ui.button("Cancel", on_click=close_popup).props("flat").classes(
                            "w-24"
                        )
            popup.open()
        except Exception as e:
            ui.notify("Query is invalid", color="negative")
            log_msg("ERROR", f"Error: {e}")

    async def delete_custom_query():
        if len(query_df[query_df["is_default"] != 1]["query_name"]) == 0:
            ui.notify("At least one custom query must exist", color="negative")
            return

        try:
            with ui.dialog() as popup:
                with ui.card().classes("w-64"):
                    name_input = ui.select(
                        options=query_df[query_df["is_default"] != 1][
                            "query_name"
                        ].tolist(),
                        label="Existing Query",
                    ).classes("w-full")

                    def close_popup():
                        popup.close()

                    async def save_popup():
                        name = name_input.value.strip()
                        if not name:
                            ui.notify("Select a existing query", color="negative")
                            return
                        # Save to queries table
                        await function_db(
                            "execute_query",
                            "delete from queries where query_name = ?",
                            (name,),
                        )
                        ui.notify(f"Query '{name}' deleted!", color="positive")
                        popup.close()
                        await refresh_query_data()
                        render_query_buttons()

                    with ui.row().classes("justify-between items-center w-full"):
                        ui.button("Delete", on_click=save_popup).classes("w-24")
                        ui.button("Cancel", on_click=close_popup).props("flat").classes(
                            "w-24"
                        )
            popup.open()
        except Exception as e:
            ui.notify("You should not see this!", color="negative")
            log_msg("ERROR", f"Error: {e}")

    with ui.row().classes("justify-between items-center w-full"):
        preset_queries = ui.element()

        def render_query_buttons():
            preset_queries.clear()
            with preset_queries:
                with ui.button_group().classes("gap-1"):
                    for _, row in query_df.iterrows():
                        ui.button(
                            row["query_name"],
                            on_click=lambda r=row: editor.set_value(r["query_sql"]),
                        ).props("flat dense").classes(
                            "text-grey-5 text-xs px-2 py-1 min-h-0 min-w-0 font-semibold"
                        )

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
                    "text-grey-5 text-xs px-2 py-1 min-h-0 min-w-0 font-semibold"
                )

    async def show_row_edit_popup(row_data, on_save_callback):
        table_name = helpers.extract_table_name(editor.value)
        table_data = TABLE_IDS.get(table_name)
        if table_data is None:
            ui.notify(f"Cannot register which table is being edited: {table_name}!")
            return

        has_seen_pk = False
        pk_data = None
        proj_df = None
        with ui.dialog() as popup:
            with ui.card().classes("w-96"):
                inputs = {}
                for field in row_data:
                    if field in table_data:
                        meta = table_data[field]

                        if meta.pk:
                            has_seen_pk = True
                            pk_data = (field, row_data.get(field, None))

                        if not meta.editable:
                            continue

                        if meta.type == "int":
                            inputs[field] = ui.number(
                                field, value=int(row_data.get(field) or 0), step=1
                            ).classes("w-full")
                        elif meta.type == "float":
                            inputs[field] = ui.number(
                                field, value=float(row_data.get(field) or 0.0), step=0.1
                            ).classes("w-full")
                        elif meta.type == "str":
                            inputs[field] = ui.input(
                                field,
                                value=str(row_data.get(field, "")),
                            ).classes("w-full")
                        elif meta.type == "long_str":
                            inputs[field] = ui.textarea(
                                field,
                                value=str(row_data.get(field, "")),
                            ).classes("w-full")
                        elif meta.type == "datetime":
                            inputs[field] = ui.input(
                                field,
                                value=str(row_data.get(field, "")),
                                placeholder="YYYY-MM-DD HH:MM:SS",
                            ).classes("w-full")
                        elif meta.type == "date":
                            inputs[field] = ui.input(
                                field,
                                value=str(row_data.get(field, "")),
                                placeholder="YYYY-MM-DD",
                            ).classes("w-full")
                        elif meta.type == "project_id" and table_name == "time":
                            proj_df = await function_db(
                                "get_project_list_from_project_id",
                                row_data.get(field, 0),
                            )
                            p_name = proj_df[
                                proj_df["project_id"] == row_data.get(field, 0)
                            ]
                            inputs[field] = ui.select(
                                label=field,
                                options=proj_df["project_name"].tolist(),
                                value=p_name["project_name"].iloc[0]
                                if (hasattr(p_name, "empty") and not p_name.empty)
                                else None,
                            ).classes("w-full")

                def close_popup():
                    popup.close()

                async def save_popup():
                    updated_data = {field: inp.value for field, inp in inputs.items()}
                    await on_save_callback(
                        row_data, updated_data, table_name, pk_data, table_data, proj_df
                    )
                    popup.close()

                with ui.row().classes("justify-end gap-2"):
                    ui.button("Save", on_click=save_popup).classes("w-24")
                    ui.button("Cancel", on_click=close_popup).props("flat").classes(
                        "w-24"
                    )
        if has_seen_pk:
            popup.open()
        else:
            ui.notify(
                "Ensure  the tables primary key is in your query!", color="negative"
            )

    async def on_cell_clicked(event):
        row_data = event.args["data"]

        async def save_row_callback(
            original_row, updated_data, table_name, pk_data, table_data, proj_df
        ):
            key_table, key = pk_data
            sql_query = f"update {table_name} set "
            for col, data in updated_data.items():
                if col == "project_id" and table_name == "time":
                    if proj_df is not None:
                        data = proj_df[proj_df["project_name"] == data][
                            "project_id"
                        ].values[0]
                    else:
                        ui.notify("Project data not found!", color="negative")
                        return

                data_type = table_data[col].type
                escape = (
                    "'" if data_type in ["date", "datetime", "str", "long_str"] else ""
                )
                sql_query += f"{col} = {escape}{data}{escape}, "
            sql_query = sql_query[:-2] + f" where {key_table} = {key}"

            await query_db(sql_query)
            ui.notify(
                f"Updating row: {key_table} = {key} in {table_name} with command:\n{sql_query}"
            )

        await show_row_edit_popup(row_data, save_row_callback)

    ui.label("Query Editors")

    initial_query = query_df[query_df["query_name"] == "time"]["query_sql"].values[0]
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
            log_msg("ERROR", f"Error: {e}")

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


# --- In-program Log ---
LOG_BUFFER = []
LOG_TEXTAREA = None
LOG_COLORS = {
    "INFO": "white",
    "WARNING": "orange",
    "ERROR": "red",
}


def log_msg(level="INFO", msg=""):
    global LOG_BUFFER, LOG_TEXTAREA, debug
    level = level.upper()
    # Always print to terminal
    getattr(logger, level.lower(), logger.info)(msg)

    # Format for web log using the same formatter
    record = logging.LogRecord(
        name=logger.name,
        level=getattr(logging, level, logging.INFO),
        pathname=__file__,
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    # Only add DEBUG to web log if debug==True; all other levels always added
    LOG_BUFFER.append({"level": level, "msg": formatted})
    if LOG_TEXTAREA:
        update_log_textarea()


def update_log_textarea():
    global LOG_BUFFER, LOG_TEXTAREA, LOG_COLORS
    if LOG_TEXTAREA:
        lines = []
        for entry in LOG_BUFFER:
            color = LOG_COLORS.get(entry["level"], "white")
            # Use HTML for color
            line = f'<span style="color:{color};"> {entry["msg"]}</span>'
            lines.append(line)
        LOG_TEXTAREA.set_content("<br>".join(lines))
        LOG_TEXTAREA.update()
        # Scroll to bottom using run_method
        LOG_TEXTAREA.run_method("scrollTo", 0, 99999)


def ui_log():
    global LOG_TEXTAREA
    with ui.card().classes("w-full max-w-2xl mx-auto my-8 p-4"):
        ui.label("Application Log").classes("text-h5 mb-4")
        LOG_TEXTAREA = ui.html(content="").classes(
            "w-full h-96 overflow-auto bg-black text-white p-2 rounded"
        )
        update_log_textarea()


def setup_ui():
    dark = ui.dark_mode()
    dark.enable()

    with ui.tabs().classes("w-full") as tabs:
        tab_time = ui.tab("Time Tracking")
        tab_data_input = ui.tab("Data Input")
        tab_ui_edits = ui.tab("DevOps Settings")
        tab_query_editors = ui.tab("Query Editors")
        tab_log = ui.tab("Log")

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
        with ui.tab_panel(tab_ui_edits):
            ui_devops_settings_entrypoint()
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


async def preload_devops():
    try:
        await setup_devops()
        await get_devops_df()
        log_msg("INFO", "DevOps preload complete.")
    except Exception as e:
        log_msg("ERROR", f"Error during DevOps preload: {e}")


def main():
    log_msg("INFO", "Starting WorkTimer!")
    setup_config()
    run_async_task(preload_devops)
    setup_db(MAIN_DB)
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
