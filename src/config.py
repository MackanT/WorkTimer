"""
Configuration Management Module

Handles loading and validation of all YAML configuration files.
Uses Pydantic models for type safety and validation.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


## Configuration Models ##


class ConfigSettings(BaseModel):
    """Settings configuration from config_settings.yml"""

    debug_mode: bool = False
    db_path: str = "worktimer.db"


class DevOpsTagConfig(BaseModel):
    """DevOps tag configuration"""

    name: str
    color: str
    icon: Optional[str] = None


class ConfigDevOpsTags(BaseModel):
    """DevOps tags configuration from devops_tags.yml"""

    devops_tags: List[DevOpsTagConfig] = Field(default_factory=list)


class ConfigData(BaseModel):
    """Data configuration from config_data.yml"""

    log_colors: Dict[str, str] = Field(default_factory=dict)
    # Add other fields as needed


class FieldConfig(BaseModel):
    """Field configuration for UI forms"""

    name: str
    label: str
    type: str
    optional: Optional[bool] = False
    options_source: Optional[str] = None
    options: Optional[List[Any]] = None
    default: Optional[Any] = None
    default_source: Optional[str] = None
    with_input: Optional[bool] = False
    parent: Optional[str] = None
    # Add other field properties as needed


class ActionConfig(BaseModel):
    """Action configuration for forms"""

    button_name: str
    function: str
    main_action: str
    main_param: str = "None"
    secondary_action: str = "None"


class EntityConfig(BaseModel):
    """Entity configuration (customer, project, task, etc.)"""

    meta: Optional[Dict[str, Any]] = None
    # Common nested blocks
    fields: Optional[List[FieldConfig]] = None
    action: Optional[ActionConfig] = None
    table: Optional[Dict[str, Any]] = None
    rows: Optional[List[Any]] = None
    add: Optional[Dict[str, Any]] = None
    update: Optional[Dict[str, Any]] = None
    delete: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"  # Allow additional fields

    @field_validator("fields", mode="before")
    @classmethod
    def _convert_fields(cls, v: Any) -> Any:
        """Convert field dicts to FieldConfig objects"""
        if not v or not isinstance(v, list):
            return v
        return [FieldConfig(**item) if isinstance(item, dict) else item for item in v]

    @field_validator("action", mode="before")
    @classmethod
    def _convert_action(cls, v: Any) -> Any:
        """Convert action dict to ActionConfig object"""
        if v and isinstance(v, dict):
            return ActionConfig(**v)
        return v

    @field_validator("table", mode="before")
    @classmethod
    def _convert_table(cls, v: Any) -> Any:
        """Convert table column dicts to TableColumnConfig objects"""
        if not v or not isinstance(v, dict):
            return v
        if "columns" in v and isinstance(v["columns"], list):
            v["columns"] = [
                TableColumnConfig(**c) if isinstance(c, dict) else c
                for c in v["columns"]
            ]
        return v


class DynamicEntityConfigBase(BaseModel):
    """Base class for configs that store arbitrary entity keys"""

    class Config:
        extra = "allow"

    @model_validator(mode="before")
    @classmethod
    def convert_to_entity_configs(cls, data: Any) -> Any:
        """Convert each top-level entity dict into EntityConfig"""
        if not isinstance(data, dict):
            return data
        return {
            k: (
                val
                if k.endswith("_page")
                else EntityConfig(**val)
                if isinstance(val, dict)
                else val
            )
            for k, val in data.items()
        }

    def model_dump(self, **kwargs) -> dict:
        """Return a plain dict where nested EntityConfig objects are also dumped"""
        extras = getattr(self, "__pydantic_extra__", {}) or {}
        return {
            k: v.model_dump() if isinstance(v, BaseModel) else v
            for k, v in extras.items()
        }


class ConfigUI(BaseModel):
    """UI configuration from config_ui.yml

    info_page:
        info: {meta: {...}}
        read_me: {meta: {...}}
    add_data_page:
        customer: {add: {...}, update: {...}}
    """

    class Config:
        extra = "allow"

    def model_dump(self, **kwargs) -> dict:
        """Return raw dict of all pages"""
        return getattr(self, "__pydantic_extra__", {}) or {}


class ConfigTasks(DynamicEntityConfigBase):
    """Tasks configuration from config_ui.yml ('task' key) - stores all entities dynamically"""

    pass


class TableColumnConfig(BaseModel):
    """Table column configuration"""

    name: str
    label: str
    field: str
    align: str = "left"
    sortable: bool = False
    style: Optional[str] = None


class QueryConfig(BaseModel):
    """Query configuration from config_query.yml"""

    query: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "allow"


class VisualConfig(BaseModel):
    """Visual configuration for customers/projects"""

    icon: str = "help"
    color: str = "grey"


class ThemeConfig(BaseModel):
    """Theme configuration for webpage"""

    primary: str
    secondary: str
    dark: str
    dark_page: str

    positive: str
    negative: str
    info: str
    warning: str

    accent: str
    muted: str
    divider: str
    toolbar_bg: str
    nav_bg: str
    border: str


class ConfigNotepad(BaseModel):
    """Notepad configuration from config_notepad.yml"""

    note_colors: Dict[str, str] = Field(default_factory=dict)
    note_icons: Dict[str, str] = Field(default_factory=dict)
    external_notes: List[Dict[str, Any]] = Field(default_factory=list)


class ConfigTaskVisuals(BaseModel):
    """Task visuals configuration from task_visuals.yml"""

    visual: Dict[str, Dict[str, VisualConfig]] = Field(default_factory=dict)

    @field_validator("visual", mode="before")
    @classmethod
    def convert_visual_dicts(cls, v: Any) -> Any:
        """Convert nested dicts to VisualConfig objects"""
        if not isinstance(v, dict):
            return v
        return {
            entity_type: {
                entity_name: VisualConfig(**visual_data)
                if isinstance(visual_data, dict)
                else visual_data
                for entity_name, visual_data in entities.items()
            }
            for entity_type, entities in v.items()
        }


class DevOpsContactConfig(BaseModel):
    """DevOps contact configuration"""

    contacts: List[str] = Field(default_factory=list)
    assignees: List[str] = Field(default_factory=list)
    default_assignee: Optional[str] = None


class ConfigDevOpsContacts(BaseModel):
    """DevOps contacts configuration from devops_contacts.yml"""

    customers: Dict[str, DevOpsContactConfig] = Field(default_factory=dict)
    default: DevOpsContactConfig = Field(default_factory=DevOpsContactConfig)

    @field_validator("customers", mode="before")
    @classmethod
    def convert_customer_dicts(cls, v):
        """Convert customer contact dicts to DevOpsContactConfig objects"""
        if not isinstance(v, dict):
            return v
        return {
            customer: DevOpsContactConfig(**contact_data)
            if isinstance(contact_data, dict)
            else contact_data
            for customer, contact_data in v.items()
        }


## Configuration Loader ##


@dataclass
class _ConfigSpec:
    """Declarative spec for a single YAML config file."""

    filename: str
    key: str
    model: type
    required: bool = True
    has_template: bool = False
    transform: Optional[Callable] = None       # raw_dict -> dict passed to model(**...)
    default_factory: Optional[Callable] = None  # () -> model instance when file is missing


class ConfigLoader:
    """Load and validate all configuration files"""

    _REGISTRY: List[_ConfigSpec] = [
        _ConfigSpec(
            filename="task_visuals.yml",
            key="task_visuals",
            model=ConfigTaskVisuals,
            required=False,
            default_factory=lambda: ConfigTaskVisuals(
                visual={
                    "customers": {"default": VisualConfig(icon="group", color="blue-grey")},
                    "projects": {"default": VisualConfig(icon="folder", color="indigo")},
                }
            ),
        ),
        _ConfigSpec(
            filename="devops_contacts.yml",
            key="devops_contacts",
            model=ConfigDevOpsContacts,
            required=False,
            has_template=True,
            default_factory=lambda: ConfigDevOpsContacts(
                customers={}, default=DevOpsContactConfig(contacts=[], assignees=[])
            ),
        ),
        _ConfigSpec(
            filename="devops_tags.yml",
            key="devops_tags",
            model=ConfigDevOpsTags,
            required=False,
            has_template=True,
            default_factory=lambda: ConfigDevOpsTags(),
        ),
        _ConfigSpec(
            filename="config_theme.yml",
            key="theme",
            model=ThemeConfig,
            required=True,
            has_template=True,
            transform=lambda d: d.get("colors", {}),
        ),
        _ConfigSpec(
            filename="config_notepad.yml",
            key="notepad",
            model=ConfigNotepad,
            required=True,
            has_template=True,
        ),
    ]

    def __init__(self, config_folder: str = "config"):
        self.config_folder = Path(config_folder)
        self.configs: Dict[str, Any] = {}

    def _load_yaml(self, filename: str, required: bool = True) -> Optional[dict]:
        """Load a YAML file with error handling"""
        filepath = self.config_folder / filename

        if not filepath.exists():
            if required:
                raise FileNotFoundError(f"Required config file not found: {filepath}")
            print(f"WARNING: {filepath} not found. Using defaults.")
            return None

        try:
            with filepath.open(encoding="utf-8") as f:
                data = yaml.safe_load(f)
                print(f"[OK] Loaded {filename}")
                return data
        except yaml.YAMLError as e:
            raise ValueError(f"Error parsing YAML in {filepath}: {e}")
        except Exception as e:
            raise RuntimeError(f"Error loading {filepath}: {e}")

    def _ensure_from_template(self, filename: str) -> None:
        """Copy <filename>.template to <filename> if the live file does not exist."""
        live = self.config_folder / filename
        template = self.config_folder / f"{filename}.template"
        if not live.exists():
            if template.exists():
                shutil.copy2(template, live)
                print(f"  Created {filename} from template")
            else:
                print(f"WARNING: Neither {filename} nor its template found.")

    def _load_spec(self, spec: _ConfigSpec) -> None:
        """Load a single config spec and store the result in self.configs."""
        if spec.has_template:
            self._ensure_from_template(spec.filename)
        raw = self._load_yaml(spec.filename, required=spec.required)
        if raw is None:
            if spec.default_factory:
                self.configs[spec.key] = spec.default_factory()
            return
        data = spec.transform(raw) if spec.transform else raw
        self.configs[spec.key] = spec.model(**data)

    def _load_settings(self) -> None:
        """Load settings from environment variables (no YAML file)."""
        db_name = os.getenv("DB_NAME", "worktimer.db")
        db_path = os.path.join("data", db_name)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.configs["settings"] = ConfigSettings(
            db_path=db_path,
            debug_mode=os.getenv("DEBUG_MODE", "false").lower() == "true",
        )
        print(
            f"  DB: {self.configs['settings'].db_path}, Debug: {self.configs['settings'].debug_mode}"
        )

    def _load_ui_config(self) -> None:
        """Load config_ui.yml and extract ui, query, and tasks sub-configs."""
        ui_yaml = self._load_yaml("config_ui.yml", required=True)
        self.configs["ui"] = ConfigUI(**ui_yaml)
        self.configs["query"] = QueryConfig(**{"query": ui_yaml.get("query", {})})
        tasks_yaml = ui_yaml.get("task", {})
        self.configs["tasks"] = ConfigTasks(**{"task": tasks_yaml})
        if tasks_yaml:
            actions = [k for k in tasks_yaml.keys() if k != "meta"]
            print(f"  Task actions: {actions}")

    def load_all(self) -> Dict[str, Any]:
        """Load and validate all configuration files"""
        if self.configs:
            return self.configs

        print("\n=== Loading Configuration Files ===")
        self._load_settings()
        self._load_ui_config()
        for spec in self._REGISTRY:
            self._load_spec(spec)
        print("=== Configuration Loading Complete ===\n")
        return self.configs

    def get(self, key: str) -> Any:
        """Get a specific configuration"""
        return self.configs.get(key)

    def get_raw_dict(self, key: str) -> dict:
        """Get configuration as raw dictionary (for backward compatibility)"""
        config = self.configs.get(key)
        if config is None:
            return {}
        if isinstance(config, BaseModel):
            return config.model_dump()
        return config

    def reload_config(self, filename: str) -> None:
        """Re-read a config file from disk and update the in-memory cache.

        Args:
            filename: The config filename (e.g. 'devops_contacts.yml').
        """
        for spec in self._REGISTRY:
            if spec.filename == filename:
                self._load_spec(spec)
                return
        print(f"WARNING: No reload handler for '{filename}'")
