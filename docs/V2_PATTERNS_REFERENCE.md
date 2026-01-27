"""
Quick Reference - Common Patterns in V2 Architecture

Copy-paste these patterns when building new pages.
"""

# ============================================================
# PATTERN 1: Basic Page Setup
# ============================================================

from nicegui import ui
from ..core import AppCore, get_config_loader
from ..services import DatabaseService

@ui.page('/example')
async def example_page():
    """Minimal page setup."""
    # Get/create app core
    core = AppCore.get_or_create(get_config_loader())
    
    # Initialize if needed
    if not core._initialized:
        await core.initialize_engines()
    
    # Dark mode
    dark = ui.dark_mode()
    dark.enable()
    
    # Your UI here
    ui.label('Hello World')


# ============================================================
# PATTERN 2: Skeleton with Dynamic Content
# ============================================================

@ui.page('/data-list')
async def data_list_page():
    core = AppCore.get_or_create(get_config_loader())
    if not core._initialized:
        await core.initialize_engines()
    
    # Container reference
    data_container = None
    
    # CREATE SKELETON
    with ui.column().classes('w-full p-4'):
        ui.label('Data List').classes('text-2xl')
        
        with ui.column() as container:
            data_container = container
            # Initially show loading
            ui.spinner(size='lg')
            ui.label('Loading data...')
    
    # POPULATE FUNCTION
    async def populate_data(data):
        """Called when data loads."""
        data_container.clear()
        
        if not data:
            with data_container:
                ui.label('No data found').classes('text-grey')
            return
        
        with data_container:
            for item in data:
                with ui.card():
                    ui.label(item['name'])
    
    # REGISTER EVENT
    core.event_bus.register('data_loaded', populate_data)
    
    # TRIGGER LOAD
    db_service = DatabaseService(core)
    db_service.load_data_async(
        "SELECT * FROM customers",
        event_name='data_loaded'
    )


# ============================================================
# PATTERN 3: Form with Dropdowns
# ============================================================

@ui.page('/form-example')
async def form_page():
    core = AppCore.get_or_create(get_config_loader())
    if not core._initialized:
        await core.initialize_engines()
    
    # Container references
    customer_select = None
    project_select = None
    
    # CREATE FORM
    with ui.card().classes('w-full max-w-md'):
        ui.label('Create Entry').classes('text-xl')
        
        customer_select = ui.select(
            label='Customer',
            options={},
            with_input=True
        )
        
        project_select = ui.select(
            label='Project',
            options={},
            with_input=True
        )
        
        description = ui.input(
            label='Description',
            placeholder='Enter description...'
        ).classes('w-full')
        
        ui.button(
            'Save',
            icon='save',
            on_click=lambda: save_entry()
        ).props('color=primary')
    
    # POPULATE DROPDOWNS
    async def populate_customers(data):
        customer_select.options = {c['customer_id']: c['name'] for c in data}
    
    async def populate_projects(data):
        project_select.options = {p['project_id']: p['name'] for p in data}
    
    # HANDLE CUSTOMER CHANGE
    async def on_customer_change(e):
        if e.value:
            # Load projects for this customer
            db_service = DatabaseService(core)
            projects = await db_service.get_projects(e.value)
            await populate_projects(projects)
    
    customer_select.on_value_change(on_customer_change)
    
    # SAVE HANDLER
    def save_entry():
        # Validate
        if not customer_select.value or not project_select.value:
            core.event_bus.notify(
                "Please fill all fields",
                type_="warning"
            )
            return
        
        # Save in background
        async def save():
            try:
                # Your save logic here
                # await core.add_data_engine.add_something(...)
                
                core.event_bus.notify(
                    "Saved successfully!",
                    type_="positive"
                )
                
                # Clear form
                customer_select.value = None
                project_select.value = None
                description.value = ""
                
            except Exception as e:
                core.event_bus.notify(
                    f"Save failed: {e}",
                    type_="negative"
                )
        
        db_service = DatabaseService(core)
        db_service.run_in_thread(save)
    
    # INITIAL LOAD
    core.event_bus.register('customers_loaded', populate_customers)
    
    db_service = DatabaseService(core)
    db_service.load_data_async(
        "SELECT * FROM customers ORDER BY name",
        event_name='customers_loaded'
    )


# ============================================================
# PATTERN 4: Long-Running Operation
# ============================================================

@ui.page('/operations')
async def operations_page():
    core = AppCore.get_or_create(get_config_loader())
    if not core._initialized:
        await core.initialize_engines()
    
    with ui.card():
        ui.label('Long Operations')
        
        ui.button(
            'Full DevOps Sync',
            icon='sync',
            on_click=lambda: full_sync()
        )
    
    def full_sync():
        """Trigger long-running operation."""
        from ..services import DevOpsService
        
        devops_service = DevOpsService(core)
        
        # User gets immediate feedback
        core.event_bus.notify(
            "Full sync started (this may take several minutes)...",
            type_="info"
        )
        
        # Runs in background, notifies when done
        devops_service.refresh_full_async()
        
        # Optional: Show progress
        # You could emit periodic events from the service
        # and update a progress bar here


# ============================================================
# PATTERN 5: Auto-Refreshing Data
# ============================================================

@ui.page('/live-data')
async def live_data_page():
    core = AppCore.get_or_create(get_config_loader())
    if not core._initialized:
        await core.initialize_engines()
    
    data_container = None
    
    with ui.column().classes('w-full p-4'):
        ui.label('Live Data (refreshes every 5s)').classes('text-xl')
        
        with ui.column() as container:
            data_container = container
    
    async def refresh_data():
        """Load fresh data."""
        db_service = DatabaseService(core)
        
        # Example: Get active timers
        query = "SELECT * FROM time_entries WHERE end_time IS NULL"
        result = core.query_engine.execute_query(query, ())
        data = result.to_dict('records') if hasattr(result, 'to_dict') else []
        
        # Update UI
        data_container.clear()
        with data_container:
            if not data:
                ui.label('No active timers').classes('text-grey')
            else:
                for timer in data:
                    with ui.card():
                        ui.label(f"Timer: {timer.get('description', 'No description')}")
    
    # Set up timer for auto-refresh
    ui.timer(5.0, refresh_data)
    
    # Initial load
    await refresh_data()


# ============================================================
# PATTERN 6: Modal Dialog
# ============================================================

@ui.page('/with-dialog')
async def dialog_page():
    core = AppCore.get_or_create(get_config_loader())
    if not core._initialized:
        await core.initialize_engines()
    
    async def show_confirm_dialog(item_id: int):
        """Show confirmation dialog."""
        result = await ui.run_javascript(
            f'confirm("Delete item {item_id}?")',
            timeout=5.0
        )
        
        if result:
            # User confirmed
            async def delete():
                try:
                    # Your delete logic here
                    # await db_service.delete_item(item_id)
                    
                    core.event_bus.notify(
                        f"Item {item_id} deleted",
                        type_="positive"
                    )
                except Exception as e:
                    core.event_bus.notify(
                        f"Delete failed: {e}",
                        type_="negative"
                    )
            
            db_service = DatabaseService(core)
            db_service.run_in_thread(delete)
    
    with ui.card():
        ui.button(
            'Delete Item',
            icon='delete',
            on_click=lambda: show_confirm_dialog(123)
        ).props('color=negative')


# ============================================================
# PATTERN 7: Multiple Event Listeners
# ============================================================

@ui.page('/multi-events')
async def multi_events_page():
    core = AppCore.get_or_create(get_config_loader())
    if not core._initialized:
        await core.initialize_engines()
    
    status_label = ui.label('Status: Ready')
    
    # Register multiple events
    async def on_data_updated(data_type):
        status_label.text = f'Status: {data_type} updated'
        core.event_bus.notify(f'{data_type} updated!', type_='positive')
    
    async def on_error(error):
        status_label.text = f'Status: Error - {error}'
    
    # Register multiple handlers for same event
    core.event_bus.register('data_updated', on_data_updated)
    core.event_bus.register('error_occurred', on_error)
    
    # Also listen to DevOps events
    async def on_devops_refresh():
        status_label.text = 'Status: DevOps refreshed'
    
    core.event_bus.register('devops_refreshed', on_devops_refresh)


# ============================================================
# PATTERN 8: Using app.storage for Navigation State
# ============================================================

@ui.page('/customer/{customer_id}')
async def customer_detail_page(customer_id: int):
    """Page with URL parameter."""
    core = AppCore.get_or_create(get_config_loader())
    if not core._initialized:
        await core.initialize_engines()
    
    # Load customer data
    db_service = DatabaseService(core)
    
    async def load_customer():
        query = "SELECT * FROM customers WHERE customer_id = ?"
        result = core.query_engine.execute_query(query, (customer_id,))
        data = result.to_dict('records') if hasattr(result, 'to_dict') else []
        
        if data:
            customer = data[0]
            with ui.card():
                ui.label(f"Customer: {customer['name']}").classes('text-2xl')
                ui.label(f"ID: {customer['customer_id']}")
        else:
            ui.label('Customer not found').classes('text-red')
    
    await load_customer()


# ============================================================
# PATTERN 9: Chaining Multiple Async Operations
# ============================================================

@ui.page('/complex-flow')
async def complex_flow_page():
    core = AppCore.get_or_create(get_config_loader())
    if not core._initialized:
        await core.initialize_engines()
    
    ui.button(
        'Start Complex Flow',
        on_click=lambda: start_flow()
    )
    
    def start_flow():
        """Chain multiple operations."""
        async def flow():
            try:
                # Step 1
                core.event_bus.notify("Step 1: Loading customers...", type_="info")
                customers = await DatabaseService(core).get_customers()
                
                # Step 2
                core.event_bus.notify("Step 2: Loading projects...", type_="info")
                projects = await DatabaseService(core).get_projects()
                
                # Step 3
                core.event_bus.notify("Step 3: Syncing DevOps...", type_="info")
                await core.devops_engine.update_devops(incremental=True)
                
                # Done
                core.event_bus.notify(
                    f"Flow complete! Loaded {len(customers)} customers, {len(projects)} projects",
                    type_="positive"
                )
                
            except Exception as e:
                core.event_bus.notify(f"Flow failed: {e}", type_="negative")
        
        DatabaseService(core).run_in_thread(flow)


# ============================================================
# PATTERN 10: Custom Event Bus for Complex Pages
# ============================================================

@ui.page('/advanced')
async def advanced_page():
    """Page with its own event handling logic."""
    core = AppCore.get_or_create(get_config_loader())
    if not core._initialized:
        await core.initialize_engines()
    
    # Use core's event bus for standard stuff
    # But you can also create your own logic:
    
    class PageState:
        """Local state management."""
        def __init__(self):
            self.loading = False
            self.data = []
        
        def set_loading(self, loading: bool):
            self.loading = loading
            update_ui()
        
        def set_data(self, data):
            self.data = data
            update_ui()
    
    state = PageState()
    loading_spinner = None
    data_display = None
    
    with ui.column():
        loading_spinner = ui.spinner(size='lg').bind_visibility_from(state, 'loading')
        data_display = ui.column()
    
    def update_ui():
        """Custom UI update logic."""
        data_display.clear()
        with data_display:
            for item in state.data:
                ui.label(item['name'])
    
    # Still use event bus for notifications
    async def load_data():
        state.set_loading(True)
        
        try:
            result = await DatabaseService(core).get_customers()
            state.set_data(result)
            core.event_bus.notify("Data loaded!", type_="positive")
        finally:
            state.set_loading(False)
    
    ui.button('Load', on_click=lambda: DatabaseService(core).run_in_thread(load_data))
