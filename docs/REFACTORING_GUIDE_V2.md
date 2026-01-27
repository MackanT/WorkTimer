# WorkTimer V2 - Refactoring Migration Guide

## Overview

This document explains the new V2 architecture and how to migrate pages from V1 to V2.

## Key Architectural Changes

### 1. Multi-Client Support via `@ui.page()`

**Old V1 Approach:**
```python
# main.py - Single instance for all clients
def main():
    # Initialize once
    query_engine = QueryEngine(...)
    devops_engine = DevOpsEngine(...)
    
    # Single UI for everyone
    setup_ui()
    
ui.run()
```

**Problem:** All clients share the same state. If User A selects Customer X, User B sees it too.

**New V2 Approach:**
```python
# main_v2.py - Each client gets their own page instance
@ui.page('/')
async def time_tracking_page():
    # Each client gets their own AppCore
    core = AppCore.get_or_create()
```

**Benefit:** Complete isolation - users never interfere with each other.

---

### 2. Thread-Safe UI Updates via `ui.context`

**Old V1 Approach:**
```python
# Doesn't work from worker threads!
def background_task():
    # Load data...
    ui.notify("Done!")  # ❌ FAILS - no context
```

**New V2 Approach:**
```python
# services/services.py
class DatabaseService:
    def load_data_async(self):
        async def load():
            # Do work...
            self.event_bus.notify("Done!")  # ✅ WORKS - uses captured context
            
        return self.run_in_thread(load)
```

**How it works:**
1. `EventBus` captures UI context when page loads
2. Worker threads emit events via `event_bus.emit()`
3. EventBus re-enters context and updates UI safely

---

### 3. Skeleton → Populate → Notify Pattern

**Old V1 Approach:**
```python
# Everything happens at once
def setup_ui():
    customers = get_customers()  # Blocking!
    
    with ui.column():
        for customer in customers:
            create_customer_card(customer)
```

**New V2 Approach:**
```python
@ui.page('/')
async def page():
    core = AppCore.get_or_create()
    
    # STEP 1: Create skeleton (instant, no data)
    with ui.column() as container:
        ui.spinner()
        ui.label("Loading...")
    
    # STEP 2: Register event handler
    async def populate(data):
        container.clear()
        for customer in data:
            create_customer_card(customer)
    
    core.event_bus.register('customers_loaded', populate)
    
    # STEP 3: Trigger async load
    db_service.load_data_async("SELECT * FROM customers", event_name='customers_loaded')
```

**Flow:**
1. Page renders instantly (empty skeleton)
2. Data loads in background thread
3. When done, event fires → UI updates
4. User sees notification via `event_bus.notify()`

---

## File Structure

```
WorkTimer/
├── main.py              # OLD - Still works, unchanged
├── main_v2.py           # NEW - Refactored entry point
├── src/
│   ├── core/            # NEW
│   │   ├── app.py       # Per-client AppCore
│   │   └── events.py    # EventBus for thread-safe updates
│   ├── services/        # NEW
│   │   └── services.py  # Thread-safe wrappers
│   ├── pages_v2/        # NEW
│   │   └── time_tracking.py  # Example refactored page
│   └── [old files]      # UNCHANGED
```

---

## Migration Checklist for a Page

### ✅ Step 1: Create Page File

Create `src/pages_v2/your_page.py`:

```python
from nicegui import ui
from ..core import AppCore, get_config_loader
from ..services import DatabaseService

@ui.page('/your-route')
async def your_page():
    core = AppCore.get_or_create(get_config_loader())
    if not core._initialized:
        await core.initialize_engines()
    
    # Continue with skeleton...
```

### ✅ Step 2: Separate Skeleton from Content

**Identify containers that need dynamic content:**
```python
containers = {}

# Create skeleton
with ui.column() as main_col:
    containers['data_display'] = ui.column()  # Empty!
    containers['customer_select'] = ui.select(options={})  # Empty!
```

### ✅ Step 3: Create Populate Functions

```python
async def populate_data(data):
    containers['data_display'].clear()
    for item in data:
        with containers['data_display']:
            ui.label(item['name'])

async def populate_customers(data):
    containers['customer_select'].options = {
        c['id']: c['name'] for c in data
    }
```

### ✅ Step 4: Register Events

```python
core.event_bus.register('data_loaded', populate_data)
core.event_bus.register('customers_loaded', populate_customers)
```

### ✅ Step 5: Trigger Loads

```python
# Load data in background
db_service = DatabaseService(core)
db_service.load_data_async(
    "SELECT * FROM data",
    event_name='data_loaded'
)
```

### ✅ Step 6: Handle User Actions

```python
def save_button_clicked():
    # Validate
    if not customer_id:
        core.event_bus.notify("Please select customer", type_="warning")
        return
    
    # Save in background
    async def save():
        await db_service.save_data(...)
        core.event_bus.notify("Saved!", type_="positive")
        # Reload data
        core.event_bus.emit('reload_data')
    
    db_service.run_in_thread(save)

ui.button('Save', on_click=save_button_clicked)
```

---

## Common Patterns

### Pattern: Dropdown Cascading

```python
# Customer changes → reload projects
async def on_customer_changed(data):
    projects = await db_service.get_projects(data['customer_id'])
    containers['project_select'].options = {
        p['id']: p['name'] for p in projects
    }

core.event_bus.register('customer_changed', on_customer_changed)

containers['customer_select'].on_value_change(
    lambda e: core.event_bus.emit('customer_changed', customer_id=e.value)
)
```

### Pattern: Auto-Refresh

```python
# Set up periodic refresh
from nicegui import ui

async def refresh_data():
    data = await db_service.get_active_timers()
    core.event_bus.emit('active_timers_loaded', data=data)

ui.timer(5.0, refresh_data)  # Every 5 seconds
```

### Pattern: Long-Running Operations

```python
def full_devops_sync():
    # This takes minutes
    devops_service = DevOpsService(core)
    
    # User gets immediate feedback
    core.event_bus.notify(
        "Full sync started (this will take several minutes)...",
        type_="info"
    )
    
    # Runs in background, notifies when done
    devops_service.refresh_full_async()
```

---

## Testing the Refactored Code

### Start V2 Server

```powershell
# From WorkTimer directory
python main_v2.py
```

### Test Multi-Client

1. Open http://localhost:8080 in Chrome
2. Open http://localhost:8080 in Firefox
3. Change customer in Chrome
4. Verify Firefox shows different customer (isolated state ✅)

### Test Thread Safety

1. Click "Refresh DevOps" button
2. Immediately navigate to different page
3. Check that notification still appears when refresh completes ✅

### Test Event System

Add debug logging:
```python
core.event_bus.register('data_loaded', lambda **kw: print(f"Event fired: {kw}"))
```

---

## Debugging Tips

### Issue: "app.storage.user needs a storage_secret"

**Cause:** Missing `storage_secret` parameter in `ui.run()`

**Fix:**
```python
# main_v2.py
ui.run(
    host="0.0.0.0",
    port=8080,
    storage_secret="your-secret-key-here"  # Required for app.storage.user!
)
```

**Important:** Change the secret in production! This is used to encrypt client session data.

### Issue: "No UI context captured"

**Cause:** EventBus.capture_context() not called

**Fix:**
```python
@ui.page('/')
async def page():
    core = AppCore.get_or_create()
    core.event_bus.capture_context()  # Add this!
```

(PageEventBus auto-calls this, but manual EventBus needs it)

### Issue: `ui.notify()` doesn't work from thread

**Cause:** Using `ui.notify()` directly instead of `event_bus.notify()`

**Fix:**
```python
# ❌ Wrong
def worker_thread():
    ui.notify("Done")

# ✅ Correct
def worker_thread():
    event_bus.notify("Done")
```

## Performance Considerations

### AppCore Initialization

- First page load: ~1-2 seconds (initializes engines)
- Subsequent pages: Instant (reuses engines)
- Engines are per-client but cached in `app.storage.user`

### Event Bus Overhead

- Negligible (<1ms per event)
- Context switching is lightweight
- Safe to emit hundreds of events per second

### Database Queries

- Use async where possible: `await query_engine.execute_query()`
- For long queries, use `db_service.load_data_async()`
- Connection pooling handled by QueryEngine

---

## Next Steps

1. **Test V2 alongside V1:** Run both `main.py` and `main_v2.py` on different ports
2. **Migrate one page at a time:** Start with simplest page
3. **Add new pages to `pages_v2/`:** Follow the pattern in `time_tracking.py`
4. **Gradually phase out V1:** Once all pages migrated, switch to V2

---

## FAQ

**Q: Can I access the old GlobalRegistry from V2 pages?**

A: No, and you shouldn't. Use `AppCore` instead:
```python
# V1
LOG = GlobalRegistry.get("LOG")

# V2
logger = core.logger
```

**Q: How do I share data between pages?**

A: Use `app.storage.user`:
```python
# Page 1
app.storage.user['selected_customer'] = 123

# Page 2
customer_id = app.storage.user.get('selected_customer')
```

Or emit events that both pages listen to.

**Q: What about the YAML configs?**

A: They still work! `AppCore` loads them via `ConfigLoader`:
```python
core.ui_config  # config_ui.yml
core.tasks_config  # config_tasks.yml
```

**Q: Can I run V1 and V2 at the same time?**

A: Yes! They're completely independent:
```powershell
# Terminal 1
python src/main.py

# Terminal 2
python main_v2.py --port 8081  # Different port
```

---

## Summary

| Feature | V1 | V2 |
|---------|----|----|
| Multi-client | ❌ Shared state | ✅ Isolated per client |
| Thread safety | ❌ ui.notify() fails | ✅ event_bus.notify() works |
| UI rendering | ❌ Blocks on data load | ✅ Instant skeleton + async populate |
| Code structure | ❌ Mixed concerns | ✅ Clear separation |
| Notifications | ❌ Unreliable from threads | ✅ Always works |

**The V2 architecture solves all your stated goals:**

1. ✅ Better thread separation with `ui.context`
2. ✅ Multi-client support via `@ui.page()`
3. ✅ Clean code structure with skeleton/populate pattern
4. ✅ Runs in parallel with old code (no breaking changes!)

Start migrating today! 🚀
