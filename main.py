from nicegui import ui
from nicegui.events import KeyEventArguments
import helpers
import asyncio
from database_new import Database
from datetime import date, datetime
# from devops import DevOpsClient

debug = True


def main():
    print("Starting WorkTimer!")


## DB SETUP ##
def setup_db(db_file: str):
    Database(db_file).initialize_db()


async def function_db(func_name: str, *args, **kwargs):
    func = getattr(Database.db, func_name)
    return await asyncio.to_thread(func, *args, **kwargs)


async def query_db(query: str):
    return await asyncio.to_thread(Database.db.fetch_query, query)


async def smart_query_db(query: str):
    return await asyncio.to_thread(Database.db.smart_query, query)


async def modify_db(query: str):
    return await asyncio.to_thread(Database.db.execute_query, query)


## UI SETUP ##
def ui_time_tracking():
    with ui.row().classes("items-center mt-4 mb-2"):
        ui.label("Time Span")
        time_options = ["Day", "Week", "Month", "Year", "All-Time", "Custom"]
        selected_time = ui.radio(time_options, value="Day").props("inline")
        selected_time
        with ui.input("Date range").classes("w-50 ml-4") as date_input:
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
                    "cursor-pointer"
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

    with ui.row().classes("items-center mt-4 mb-2"):
        ui.label("Display Options")
        radio_display_selection = ui.radio(["Time", "Bonus"], value="Time").props(
            "inline"
        )

    date_input.value = helpers.get_range_for(selected_time.value)
    date_input.on("update:model-value", set_custom_radio)
    date_picker.on("update:model-value", set_custom_radio)
    selected_time.on("update:model-value", on_radio_time_change)
    radio_display_selection.on("update:model-value", on_radio_type_change)

    container = ui.element()

    async def on_checkbox_change(event, checked, customer_id, project_id):
        print(event, checked, customer_id, project_id)
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

    # Store references to value labels and their associated project rows
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
                .style("flex-wrap:nowrap; min-width:100vw;")
            ):
                for (customer_id, customer_name), group in customers:
                    with (
                        ui.column()
                        .classes("items-start")
                        .style(
                            "flex:1 1 320px; min-width:320px; max-width:480px; margin:0 12px"
                        )
                    ):
                        ui.label(str(customer_name)).classes("text-h6")
                        for _, project in group.iterrows():
                            with (
                                ui.row()
                                .classes("items-center w-full")
                                .style(
                                    "display: grid; grid-template-columns: 20px 1fr 64px; align-items: center; margin-bottom:2px; min-height:20px;"
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

    # Function to update only the value labels' text
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
    with ui.splitter(value=30).classes("w-full h-56") as splitter:
        with splitter.before:
            with ui.tabs().props("vertical").classes("w-full") as tabs:
                mail = ui.tab("Customers", icon="mail")
                alarm = ui.tab("Projects", icon="alarm")
                movie = ui.tab("Bonuses", icon="movie")
        with splitter.after:
            with (
                ui.tab_panels(tabs, value=mail)
                .props("vertical")
                .classes("w-full h-full")
            ):
                with ui.tab_panel(mail):
                    ui.label("Customers").classes("text-h4")
                    ui.label("Content of customers")
                with ui.tab_panel(alarm):
                    ui.label("Projects").classes("text-h4")
                    ui.label("Content of projects")
                with ui.tab_panel(movie):
                    ui.label("Bonuses").classes("text-h4")
                    ui.label("Content of bonuses")


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
            df = await smart_query_db(query)
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
    # Combine settings and time tracking in one tab
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

    # setup_devops()
    setup_ui()
    ui.run()
