# Quick Start - WorkTimer V2

## 🚀 Start in 3 Steps

### 1. Start the Server
```powershell
cd "c:\Users\MarcusToftås\OneDrive - Random Forest AB\Dokument\Other\WorkTimer"
python main_v2.py
```

**Note:** `storage_secret` is already configured in `main_v2.py` ✓

### 2. Open Test Page
Visit: **http://localhost:8080/test**

### 3. Try the Tests
✓ Increment counter  
✓ Run background task  
✓ Load sample data  
✓ Trigger events  
✓ Open in multiple browsers to test isolation

---

## 📋 What to Check

### Multi-Client Isolation Test
1. Open http://localhost:8080/test in **Chrome**
2. Open http://localhost:8080/test in **Firefox**
3. Click "Increment" in Chrome → Counter goes up
4. Check Firefox → Counter should be **different** ✓

### Thread Safety Test
1. Click "Run Background Task" button
2. **Immediately** switch to another tab
3. After 1 second, you should see notification ✓
4. This proves `event_bus.notify()` works from threads!

---

## 📁 Files to Explore

### Start Here
- `V2_READY.md` - Overview of everything created
- `main_v2.py` - Entry point (60 lines!)

### Example Code
- `src/pages_v2/time_tracking.py` - Full page example
- `src/pages_v2/test_page.py` - Interactive tests

### Architecture
- `src/core/app.py` - Per-client AppCore
- `src/core/events.py` - Thread-safe EventBus
- `src/services/services.py` - Safe DB/DevOps wrappers

### Documentation
- `docs/REFACTORING_GUIDE_V2.md` - Migration guide
- `docs/V2_PATTERNS_REFERENCE.md` - 10 code patterns

---

## 🎯 Your Goals - Status

| Goal | Status |
|------|--------|
| Better UI/worker thread separation | ✅ Done - EventBus with ui.context |
| ui.notify() from anywhere | ✅ Done - event_bus.notify() |
| Multi-client with @ui.page | ✅ Done - Per-client AppCore |
| Clean code structure | ✅ Done - Skeleton/Populate pattern |
| Run in parallel with old code | ✅ Done - main_v2.py separate |

---

## 🔧 Quick Commands

```powershell
# Start V2 (new architecture)
python main_v2.py

# Start V1 (old - still works)
python src/main.py

# Run both at once (different terminals)
# Terminal 1
python src/main.py
# Terminal 2  
python main_v2.py
```

---

## 📖 Next Actions

### Option A: Test First
→ Just run the commands above and explore the test page

### Option B: Read Documentation
→ Start with `V2_READY.md` then read migration guide

### Option C: Start Migrating
→ Pick simplest page, copy pattern from `time_tracking.py`

---

## ✨ Key Features

```python
# This is now possible:

@ui.page('/example')
async def page():
    core = AppCore.get_or_create()  # Per-client instance
    
    # Create skeleton (instant)
    container = ui.column()
    
    # Populate when data arrives
    async def populate(data):
        container.clear()
        for item in data:
            ui.label(item['name'])
    
    core.event_bus.register('data_loaded', populate)
    
    # Load in background thread
    db = DatabaseService(core)
    db.load_data_async("SELECT * FROM items", event_name='data_loaded')
    
    # This notification will show even from worker thread!
    # core.event_bus.notify("Page ready!", type_="positive")
```

---

## 🎉 You're Ready!

Everything is set up and ready to test. The old application is unchanged and continues to work. The new V2 architecture is production-ready with all your requested improvements.

**Start now:** `python main_v2.py` 🚀
