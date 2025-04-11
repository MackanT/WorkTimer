import dearpygui.dearpygui as dpg
from datetime import datetime
import pandas as pd

dpg.create_context()

# Create a pandas DataFrame with customer, project, state, and time info
data = {
    "customer_id": [0, 0, 1, 1, 1],
    "customer_name": ['Rowico', 'Rowico', 'Random Forest', 'Random Forest', 'Random Forest'],
    "project_id": [0, 1, 2, 3, 4],
    "project_name": ['Arbete', 'Staffling', 'Arbete', 'WorkTimer', 'Övertid'],
    "initial_state": [True, False, True, False, True],
    "initial_text": ['1 h 30 min', '0 h 0 min', '2 h 0 min', '0 h 0 min', '3 h 15 min']
}
df = pd.DataFrame(data)


## Update UI Labels
def update_total_time(customer_id: int, label_value: str) -> None:
    dpg.set_value(f"total_{customer_id}", label_value)

def update_individual_time(customer_id: int, project_id: int, label_value: str) -> None:
    dpg.set_value(f"time_{customer_id}_{project_id}", label_value)


## Button Functions
def time_span_callback(sender, app_data):
    print(f"Selected Time Span: {dpg.get_value("time_span_group")}")

def data_type_callback(sender, app_data):
    print(f"Selected Data Type: {dpg.get_value("data_type_group")}")

def project_button_callback(sender, app_data, user_data):
    customer_id, project_id = user_data
    print(f"Clicked project button - Customer ID: {customer_id}, Project ID: {project_id}")

# UI
with dpg.window(label="Work Timer v2", width=500, height=600):
    
    ## Settings
    with dpg.collapsing_header(label="Settings", default_open=True):
        with dpg.group(horizontal=True): # Time Span
            with dpg.group():
                dpg.add_text("Select Time Span:")
                time_span_options = ["Day", "Week", "Month", "Year", "All-Time"]
                dpg.add_radio_button(label="Time Span", items=time_span_options, tag="time_span_group", callback=time_span_callback)

            with dpg.group(): # Data Type
                dpg.add_text("Select Data Type:")
                data_type_options = ["Time", "Cost"]
                dpg.add_radio_button(label="Data Type", items=data_type_options, tag="data_type_group", callback=data_type_callback)


    # "Queries" Section
    with dpg.collapsing_header(label="Queries", default_open=True):
        # Multi-row Text Input (with scrollable lines)
        with dpg.group():
            dpg.add_text("Enter Query:")
            dpg.add_input_text(multiline=True, width=480, height=100, tag="query_input", callback=None)

        # Box for displaying tabular data
        with dpg.group():
            dpg.add_text("Tabular Data:")

            # Ensure the table is not inside any handler_registry
            with dpg.table(tag="data_table", resizable=True, width=480):
                # Define columns
                dpg.add_table_column(label="Customer ID")
                dpg.add_table_column(label="Customer Name")
                dpg.add_table_column(label="Project ID")
                dpg.add_table_column(label="Project Name")

                # Add data from the DataFrame
                # for index, row in df.iterrows():
                #     # Add a row before adding cells
                #     with dpg.table_row():
                #         # Add each item in the row as a table cell, ensuring conversion to string
                #         dpg.add_table_cell(content=str(row["customer_id"]))
                #         dpg.add_table_cell(content=row["customer_name"])
                #         dpg.add_table_cell(content=str(row["project_id"]))
                #         dpg.add_table_cell(content=row["project_name"])


    # Customer and project UI
    for customer_id in df['customer_id'].unique():
        customer_name = df.loc[df['customer_id'] == customer_id, 'customer_name'].iloc[0]
        with dpg.collapsing_header(label=customer_name, default_open=True):
            total_text = f"Total: 0 h 0 min"
            dpg.add_text(total_text, tag=f"total_{customer_id}")
            for _, row in df[df['customer_id'] == customer_id].iterrows():
                project_id = row['project_id']
                project_name = row['project_name']
                initial_state = row['initial_state']
                initial_text = row['initial_text']
                
                with dpg.group(horizontal=True):
                    # Set the initial state of the checkbox based on the DataFrame
                    dpg.add_checkbox(
                        label=project_name,
                        callback=project_button_callback,
                        user_data=(customer_id, project_id),
                        default_value=initial_state
                    )
                    # Set the initial text for the project time based on the DataFrame
                    dpg.add_text(initial_text, tag=f"time_{customer_id}_{project_id}")




# with dpg.window(label="Work Timer v2", width=500, height=600):
#     for customer_id in df['customer_id'].unique():
#         customer_name = df.loc[df['customer_id'] == customer_id, 'customer_name'].iloc[0]
#         with dpg.collapsing_header(label=customer_name, default_open=True):
#             total_text = f"Total: 0 h 0 min"
#             dpg.add_text(total_text, tag=f"total_{customer_id}")
#             for _, row in df[df['customer_id'] == customer_id].iterrows():
#                 project_id = row['project_id']
#                 project_name = row['project_name']
#                 initial_state = row['initial_state']
#                 initial_text = row['initial_text']
                
#                 with dpg.group(horizontal=True):
#                     # Set the initial state of the checkbox based on the DataFrame
#                     dpg.add_checkbox(
#                         label=project_name,
#                         callback=project_button_callback,
#                         user_data=(customer_id, project_id),
#                         default_value=initial_state
#                     )
#                     # Set the initial text for the project time based on the DataFrame
#                     dpg.add_text(initial_text, tag=f"time_{customer_id}_{project_id}")



dpg.create_viewport(title='Work Timer v2', width=500, height=650)
dpg.setup_dearpygui()
dpg.show_viewport()

update_total_time(0, "Total: 3 h 10 min")

dpg.start_dearpygui()
dpg.destroy_context()