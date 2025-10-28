# UI Styling Refactoring Plan

## Problem
The current UI sizing/styling code is inconsistent and scattered:
- Hardcoded class strings like `"w-64"`, `"w-full flex-1"` throughout the code
- Complex conditional logic for determining widget sizes
- No clear standard for when to use what size
- Difficult to make global UI changes

## Solution: Centralized Styling System

### 1. Configuration File (`config/config_ui_styles.yml`)
Created a YAML file defining:
- **Widget Widths**: Standard sizes (compact, standard, wide, full, etc.)
- **Container Widths**: Card/panel max-widths (xs, sm, md, lg, xl, xxl, full)
- **Layout Classes**: Common layout patterns (form_row, form_column, card, etc.)
- **Widget-Specific Styles**: Special styling for codemirror, html_preview, etc.
- **Default Size Mapping**: Which size each widget type should use by default
- **Wide Widget Detection**: Which widget types trigger "wide layout mode"

### 2. UIStyles Class (`helpers.py`)
Created a singleton class that:
- Loads the YAML configuration once
- Provides clean API methods to get styles:
  - `get_widget_width(size_name)` - Get width classes
  - `get_container_width(size_name)` - Get container max-width
  - `get_layout_classes(layout_name)` - Get layout classes
  - `get_widget_style(widget_type, mode)` - Get widget-specific styles
  - `get_default_size(widget_type)` - Get default size for a widget type
  - `is_wide_widget(widget_type)` - Check if widget triggers wide mode

### 3. Benefits
✅ **Single source of truth** for all UI sizing
✅ **Easy global changes** - edit YAML, not scattered code
✅ **Consistent UI** - all widgets use same size definitions
✅ **Self-documenting** - YAML explains what each size means
✅ **Flexible** - can add new sizes/styles without code changes
✅ **Type-safe defaults** - each widget type has a sensible default

## Next Steps

### Phase 1: Refactor `build_generic_tab_panel` (RECOMMENDED TO START HERE)
1. Replace the complex width detection logic with:
   ```python
   # Check if ANY row has wide widgets
   has_wide_layout = any(
       UI_STYLES.is_wide_widget(f.get("type")) 
       for row in rows_config 
       for f in get_row_fields(row)
   )
   
   # Get appropriate widget size
   if has_wide_layout:
       widget_size = "full"  # All widgets in wide mode
   else:
       # Use widget type's default size
       widget_size = UI_STYLES.get_default_size(field["type"])
   
   # Get the actual classes
   widget_classes = UI_STYLES.get_widget_width(widget_size)
   ```

2. Replace hardcoded row/column classes:
   ```python
   with ui.column().classes(UI_STYLES.get_layout_classes("form_column")):
       with ui.row().classes(UI_STYLES.get_layout_classes("form_row")):
   ```

3. Use configured container width:
   ```python
   # Instead of: width parameter with hardcoded "4", "7", etc.
   # Use: container_size="md" or "xxl"
   max_width = UI_STYLES.get_container_width(container_size)
   with ui.card().classes(f"{UI_STYLES.get_layout_classes('card')} max-w-{max_width}xl"):
   ```

### Phase 2: Refactor `make_input_row`
1. Remove the `input_width` parameter logic
2. For each widget, get its size from config:
   ```python
   size_name = UI_STYLES.get_default_size(field["type"])
   widget_classes = UI_STYLES.get_widget_width(size_name)
   ```

3. Apply widget-specific styles:
   ```python
   if ftype == "codemirror":
       styles = UI_STYLES.get_widget_style("codemirror", "full" if has_wide else "standard")
       editor.classes(f"{widget_classes} {styles['classes']}")
       editor.style(styles['style'])
   ```

### Phase 3: Update YAML Configs (Optional)
Add a `width` or `size` field to field definitions:
```yaml
- name: description_editor
  label: Description Editor
  type: codemirror
  size: full  # Override default if needed
```

### Phase 4: Clean Up
- Remove old `_double_width_class()` function
- Remove hardcoded size logic
- Simplify conditional branches

## Example Usage

```python
# Get a widget width
width = UI_STYLES.get_widget_width("standard")  # Returns "w-64"
width = UI_STYLES.get_widget_width("full")      # Returns "w-full flex-1"

# Get container width for a card
container = UI_STYLES.get_container_width("xl")  # Returns "6" for max-w-6xl

# Get layout classes
row_classes = UI_STYLES.get_layout_classes("form_row")  # Returns "w-full gap-4"

# Get default size for a widget type
size = UI_STYLES.get_default_size("codemirror")  # Returns "full"
classes = UI_STYLES.get_widget_width(size)       # Returns "w-full flex-1"

# Check if widget triggers wide mode
is_wide = UI_STYLES.is_wide_widget("codemirror")  # Returns True
is_wide = UI_STYLES.is_wide_widget("select")     # Returns False
```

## Testing Plan
1. Run application - should work identically to before
2. Change a size in YAML (e.g., make "standard" → "w-80")
3. Verify all standard widgets now use w-80
4. Change back and verify

## Future Enhancements
- Add color schemes to YAML
- Add spacing/gap configurations
- Add responsive breakpoint definitions
- Per-tab or per-form size overrides in field configs
