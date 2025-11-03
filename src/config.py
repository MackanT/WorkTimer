"""
Configuration Management Module

Handles loading and validation of all YAML configuration files.
Uses Pydantic models for type safety and validation.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


## Configuration Models ##


class ConfigSettings(BaseModel):
    """Settings configuration from config_settings.yml"""

    debug_mode: bool = False
    db_name: str = "data_dpg.db"


class DevOpsTagConfig(BaseModel):
    """DevOps tag configuration"""

    name: str
    color: str
    icon: Optional[str] = None


class ConfigData(BaseModel):
    """Data configuration from config_data.yml"""

    devops_tags: List[DevOpsTagConfig] = Field(default_factory=list)
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
            k: EntityConfig(**val) if isinstance(val, dict) else val
            for k, val in data.items()
        }

    def model_dump(self, **kwargs) -> dict:
        """Return a plain dict where nested EntityConfig objects are also dumped"""
        extras = getattr(self, "__pydantic_extra__", {}) or {}
        return {
            k: v.model_dump() if isinstance(v, BaseModel) else v
            for k, v in extras.items()
        }


class ConfigUI(DynamicEntityConfigBase):
    """UI configuration from config_ui.yml - stores all entities dynamically"""

    pass


class ConfigTasks(DynamicEntityConfigBase):
    """Tasks configuration from config_tasks.yml - stores all entities dynamically"""

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


class ConfigLoader:
    """Load and validate all configuration files"""

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
                print(f"✓ Loaded {filename}")
                return data
        except yaml.YAMLError as e:
            raise ValueError(f"Error parsing YAML in {filepath}: {e}")
        except Exception as e:
            raise RuntimeError(f"Error loading {filepath}: {e}")

    def load_all(self) -> Dict[str, Any]:
        """Load and validate all configuration files"""
        print("\n=== Loading Configuration Files ===")

        # Load settings (required)
        settings_data = self._load_yaml("config_settings.yml", required=True)
        self.configs["settings"] = ConfigSettings(**settings_data)
        print(
            f"  DB: {self.configs['settings'].db_name}, Debug: {self.configs['settings'].debug_mode}"
        )

        # Load data config (required)
        data_yaml = self._load_yaml("config_data.yml", required=True)
        self.configs["data"] = ConfigData(**data_yaml)

        # Load UI config (required)
        ui_yaml = self._load_yaml("config_ui.yml", required=True)
        self.configs["ui"] = ConfigUI(**ui_yaml)

        # Load query config (required)
        query_yaml = self._load_yaml("config_query.yml", required=True)
        self.configs["query"] = QueryConfig(**query_yaml)

        # Load tasks config (required)
        tasks_yaml = self._load_yaml("config_tasks.yml", required=True)
        self.configs["tasks"] = ConfigTasks(**tasks_yaml)
        if "task" in tasks_yaml:
            actions = [k for k in tasks_yaml["task"].keys() if k != "meta"]
            print(f"  Task actions: {actions}")

        # Load task visuals (optional with defaults)
        visuals_yaml = self._load_yaml("task_visuals.yml", required=False)
        if visuals_yaml:
            self.configs["task_visuals"] = ConfigTaskVisuals(**visuals_yaml)
        else:
            print("  Using default task visuals (run scripts/generate_task_visuals.py)")
            self.configs["task_visuals"] = ConfigTaskVisuals(
                visual={
                    "customers": {
                        "default": VisualConfig(icon="group", color="blue-grey")
                    },
                    "projects": {
                        "default": VisualConfig(icon="folder", color="indigo")
                    },
                }
            )

        # Load DevOps contacts (optional with defaults)
        contacts_yaml = self._load_yaml("devops_contacts.yml", required=False)
        if contacts_yaml:
            self.configs["devops_contacts"] = ConfigDevOpsContacts(**contacts_yaml)
            customer_count = len(self.configs["devops_contacts"].customers)
            print(f"  DevOps contacts: {customer_count} customers")
        else:
            print("  Using empty DevOps contacts (copy devops_contacts.yml.template)")
            self.configs["devops_contacts"] = ConfigDevOpsContacts(
                customers={}, default=DevOpsContactConfig(contacts=[], assignees=[])
            )

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
