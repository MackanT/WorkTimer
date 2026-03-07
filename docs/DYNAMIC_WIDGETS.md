# Dynamic Widget System

Clean, maintainable class-based UI architecture that eliminates complex helper functions.

## Overview

The dynamic widget system uses inheritance to create self-refreshing widgets that:
- **Auto-wire parent-child relationships** - Changes in parent dropdown automatically refresh child
- **Handle data fetching** - Each widget knows how to refresh its own data
- **Proxy to underlying NiceGUI widgets** - Full access to standard widget methods
- **Eliminate complex helpers** - No more `make_input_row` or `bind_parent_relations`

## Architecture

```
DynamicWidget (Base)
├─ DynamicDropDown (select fields)
├─ DynamicInput (text fields)
├─ DynamicNumber (number fields)
├─ DynamicDate (date fields)
└─ DynamicSwitch (toggle fields)
```

## Base Class

All widgets inherit from `DynamicWidget`:

```python
class DynamicWidget(ABC):
    def __init__(
        self,
        name: str,
        data_fetcher: Callable,  # async fn(options_source, parent_val) -> data
        options_source: str = "",  # Key in data sources dict
        parent: Optional[DynamicWidget] = None,  # Parent widget for dependencies
        label: str = "",
        initial_value: Any = None,
        field_config: Dict = None,  # Full field config from YAML
        **widget_kwargs
    ):
        # Creates widget via _create_widget()
        # Auto-wires to parent if provided
        # Sets initial value
```

## Widget Types

### DynamicDropDown
```python
dd = DynamicDropDown(
    name="project_name",
    options_source="project_data",
    data_fetcher=data_fetcher,
    parent=customer_dd,  # Auto-refreshes when customer changes
    label="Project",
    field_config={"with_input": True, "allow_custom": True}
)
```

### DynamicInput
```python
di = DynamicInput(
    name="description",
    label="Description",
    initial_value="Default text"
)
```

### DynamicNumber
```python
dn = DynamicNumber(
    name="hours",
    label="Hours",
    initial_value=0
)
```

### DynamicDate
```python
dd = DynamicDate(
    name="start_date",
    label="Start Date",
    field_config={"default": "2024-01-01"}
)
```

### DynamicSwitch
```python
ds = DynamicSwitch(
    name="is_active",
    label="Active",
    initial_value=True
)
```

## Usage Pattern

### 1. Create Data Fetcher
```python
async def data_fetcher(source_key, parent_val=None):
    """Fetch fresh data from database"""
    fresh = await prepare_data_sources(core, entity_type, operation)
    if source_key not in fresh:
        return []
    
    data = fresh[source_key]
    
    # Handle nested data (parent-child relationship)
    if parent_val and isinstance(data, dict):
        return data.get(parent_val, [])
    
    return data
```

### 2. Create Widgets
```python
widgets = {}
dynamic_widgets = []
parent_map = {}

for field in fields:
    field_type = field.get("type", "input")
    parent_field = field.get("parent")
    parent_widget = parent_map.get(parent_field) if parent_field else None
    
    # Get widget class from registry
    widget_class = WIDGET_CLASSES[field_type]
    
    # Create widget instance
    dw = widget_class(
        name=field["name"],
        data_fetcher=data_fetcher,
        options_source=field.get("options_source", ""),
        parent=parent_widget,
        label=field.get("label", field["name"]),
        initial_value=field.get("default"),
        field_config=field,
    )
    
    widgets[field["name"]] = dw
    parent_map[field["name"]] = dw
    dynamic_widgets.append(dw)
```

### 3. Refresh All Widgets
```python
async def refresh_all_widgets():
    """Refresh all dynamic widgets after save"""
    for dw in dynamic_widgets:
        await dw.refresh()
```

## Widget Registry

Map field types to widget classes:

```python
WIDGET_CLASSES = {
    'select': DynamicDropDown,
    'input': DynamicInput,
    'text': DynamicInput,  # Alias
    'number': DynamicNumber,
    'date': DynamicDate,
    'switch': DynamicSwitch,
}
```

## Value Access

All widgets proxy value and methods to underlying NiceGUI widget:

```python
# Get value
value = dw.value

# Set value  
dw.value = "New value"

# Register handler
dw.on_value_change(lambda e: print(e.value))

# Apply styling
dw.classes("w-full")
dw.props("outlined")
dw.style("color: red")

# Update widget
dw.update()
```

## Parent-Child Relationships

Parent-child relationships are auto-wired in constructor:

```python
# Create parent
customer_dd = DynamicDropDown(name="customer", ...)

# Create child - auto-wires to parent
project_dd = DynamicDropDown(
    name="project",
    parent=customer_dd,  # Will refresh when customer changes
    ...
)

# When customer value changes, project automatically refreshes
```

## Benefits Over Old System

### Before (Complex Helpers)
```python
# Separate select from non-select fields
select_fields = [f for f in fields if f.get("type") == "select"]
non_select_fields = [f for f in fields if f.get("type") != "select"]

# Create dropdowns manually
for f in select_fields:
    parent_dd = parent_map.get(f.get("parent"))
    dd = DynamicDropDown(...)
    widgets[f["name"]] = dd

# Use make_input_row for other fields (864 lines!)
if non_select_fields:
    other_widgets, pending_relations = helpers.make_input_row(
        non_select_fields, defer_parent_wiring=True
    )
    widgets.update(other_widgets)

# Wire up parent relations (1470 lines!)
if pending_relations:
    helpers.bind_parent_relations(
        widgets, pending_relations, {}, data_sources
    )
```

### After (Clean OOP)
```python
# Loop through all fields once
for field in fields:
    widget_class = WIDGET_CLASSES[field["type"]]
    parent_widget = parent_map.get(field.get("parent"))
    
    dw = widget_class(
        name=field["name"],
        parent=parent_widget,  # Auto-wires
        ...
    )
    
    widgets[field["name"]] = dw
```

## Extending the System

Add new widget types:

```python
class DynamicTextArea(DynamicWidget):
    """Multi-line text input"""
    
    def _create_widget(self):
        return ui.textarea(label=self.label, **self.widget_kwargs)
    
    async def _refresh_impl(self, parent_val):
        # Implement refresh logic if needed
        pass

# Register it
WIDGET_CLASSES['textarea'] = DynamicTextArea
```

## Configuration

Widgets read from `config_ui.yml` field definitions:

```yaml
customer:
  add:
    fields:
      - name: customer_name
        type: select
        label: Customer
        options_source: customer_data
        with_input: true
        allow_custom: true
        
      - name: hours
        type: number
        label: Hours
        default: 8
        
      - name: start_date
        type: date
        label: Start Date
```

All field config properties are passed to widgets via `field_config` parameter.
