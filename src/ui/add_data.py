"""
Add Data UI Module

This module provides interfaces for adding and updating data in the database,
including customers, projects, bonuses, and DevOps work items.
It also includes database management tools for comparing and updating databases.

Refactored to use DataPrepRegistry and EntityFormBuilder pattern.
Lines reduced from 850 → ~280 (67% reduction).
"""

import asyncio
from datetime import date
from nicegui import ui

from .. import helpers
from ..globals import GlobalRegistry
from .data_registry import DataPrepRegistry
from .form_builder import EntityFormBuilder
from .database_tools import build_database_compare_tab, build_database_update_tab
from .devops_handlers import DevOpsWorkItemHandlers


# ============================================================================
# Data Preparation Functions (Registered with DataPrepRegistry)
# ============================================================================


@DataPrepRegistry.register("customer", "Add")
def prep_customer_add(**kwargs):
    """Prepare data for customer Add tab."""
    return {}


@DataPrepRegistry.register("customer", "Update")
def prep_customer_update(**kwargs):
    """Prepare data for customer Update tab."""
    AD = GlobalRegistry.get("AD")
    active_data = helpers.filter_df(AD.df, {"c_current": 1})
    customer_names = helpers.get_unique_list(active_data, "customer_name")

    # Build nested dicts for org_url and pat_token per customer
    org_urls = {}
    pat_tokens = {}
    new_customer_names = {}

    for customer in customer_names:
        filtered = helpers.filter_df(AD.df, {"customer_name": customer})
        org_urls[customer] = helpers.get_unique_list(filtered, "org_url")
        pat_tokens[customer] = helpers.get_unique_list(filtered, "pat_token")
        new_customer_names[customer] = [customer]

    return {
        "customer_data": customer_names,
        "new_customer_name": new_customer_names,
        "org_url": org_urls,
        "pat_token": pat_tokens,
    }


@DataPrepRegistry.register("customer", "Disable")
def prep_customer_disable(**kwargs):
    """Prepare data for customer Disable tab."""
    AD = GlobalRegistry.get("AD")
    active_data = helpers.filter_df(AD.df, {"c_current": 1})
    customer_names = helpers.get_unique_list(active_data, "customer_name")
    return {"customer_data": customer_names}


@DataPrepRegistry.register("customer", "Reenable")
def prep_customer_reenable(**kwargs):
    """Prepare data for customer Reenable tab."""
    AD = GlobalRegistry.get("AD")
    active_data = helpers.filter_df(AD.df, {"c_current": 1})

    customer_names = helpers.get_unique_list(active_data, "customer_name")
    candidate_names = helpers.filter_df(
        AD.df,
        {"c_current": 0},
        return_as="distinct_list",
        column="customer_name",
    )
    reenable_names = sorted(list(set(candidate_names) - set(customer_names)))
    return {"customer_data": reenable_names}


@DataPrepRegistry.register("project", "Add")
def prep_project_add(**kwargs):
    """Prepare data for project Add tab."""
    AD = GlobalRegistry.get("AD")
    active_data = helpers.filter_df(AD.df, {"c_current": 1})
    active_customer_names = helpers.get_unique_list(active_data, "customer_name")
    return {"customer_data": active_customer_names}


@DataPrepRegistry.register("project", "Update")
def prep_project_update(**kwargs):
    """Prepare data for project Update tab."""
    AD = GlobalRegistry.get("AD")
    active_data = helpers.filter_df(AD.df, {"c_current": 1})
    active_customer_names = helpers.get_unique_list(active_data, "customer_name")

    project_names = {}
    new_project_name = {}
    new_git_id = {}

    for customer in active_customer_names:
        filtered = helpers.filter_df(
            active_data, {"customer_name": customer, "p_current": 1}
        )
        project_names[customer] = helpers.get_unique_list(filtered, "project_name")
        for project in project_names[customer]:
            filtered_cust = helpers.filter_df(filtered, {"project_name": project})
            new_project_name[project] = [project]
            new_git_id[project] = helpers.get_unique_list(filtered_cust, "git_id")

    return {
        "customer_data": active_customer_names,
        "project_names": project_names,
        "new_project_name": new_project_name,
        "new_git_id": new_git_id,
    }


@DataPrepRegistry.register("project", "Disable")
def prep_project_disable(**kwargs):
    """Prepare data for project Disable tab."""
    AD = GlobalRegistry.get("AD")
    active_data = helpers.filter_df(AD.df, {"c_current": 1})
    active_customer_names = helpers.get_unique_list(active_data, "customer_name")

    project_names = {}
    for customer in active_customer_names:
        filtered = helpers.filter_df(
            active_data, {"customer_name": customer, "p_current": 1}
        )
        project_names[customer] = helpers.get_unique_list(filtered, "project_name")

    return {
        "customer_data": active_customer_names,
        "project_names": project_names,
    }


@DataPrepRegistry.register("project", "Reenable")
def prep_project_reenable(**kwargs):
    """Prepare data for project Reenable tab."""
    AD = GlobalRegistry.get("AD")
    active_data = helpers.filter_df(AD.df, {"c_current": 1})
    active_customer_names = helpers.get_unique_list(active_data, "customer_name")

    project_names = {}
    for customer in active_customer_names:
        filtered = helpers.filter_df(
            active_data, {"customer_name": customer, "p_current": 0}
        )
        project_names[customer] = helpers.get_unique_list(filtered, "project_name")

    return {
        "customer_data": active_customer_names,
        "project_names": project_names,
    }


@DataPrepRegistry.register("bonus", "Add")
def prep_bonus_add(**kwargs):
    """Prepare data for bonus Add tab."""
    # Return today's date for auto-population
    return {"start_date": [str(date.today())]}


@DataPrepRegistry.register("devops_work_item", "Add")
def prep_devops_work_item_add(**kwargs):
    """Prepare data for DevOps work item Add tab."""
    DO = GlobalRegistry.get("DO")
    config_devops_contacts = GlobalRegistry.get("config_devops_contacts")
    DEVOPS_TAGS = GlobalRegistry.get("DEVOPS_TAGS")

    # Check if DevOps data is available
    if DO.df is None or DO.df.empty:
        return {}

    # Get unique customer names from DevOps data
    customer_names = helpers.get_unique_list(DO.df, "customer_name")
    work_items = {}
    parent_names = {}

    for customer in customer_names:
        filtered = helpers.filter_df(DO.df, {"customer_name": customer})
        work_items[customer] = [row["display_name"] for _, row in filtered.iterrows()]

        # Get parent items for different work item types
        epics_filtered = helpers.filter_df(
            DO.df, {"customer_name": customer, "type": "Epic"}
        )
        features_filtered = helpers.filter_df(
            DO.df, {"customer_name": customer, "type": ["Epic", "Feature"]}
        )
        parent_names[customer] = {
            "Epic": [],  # Epics have no parents
            "Feature": [
                row["display_name"] for _, row in epics_filtered.iterrows()
            ],  # Features parent to Epics
            "User Story": [
                row["display_name"] for _, row in features_filtered.iterrows()
            ],  # User Stories parent to Epics/Features
        }

    # Prepare customer-specific contacts and assignees
    contact_persons = {}
    assignees = {}
    default_assignee = {}

    for customer in customer_names:
        # Get customer-specific data from config
        customer_data = config_devops_contacts.get("customers", {}).get(customer, {})
        default_data = config_devops_contacts.get("default", {})

        # Use customer-specific contacts, or fall back to defaults
        contact_persons[customer] = customer_data.get(
            "contacts", default_data.get("contacts", [])
        )
        assignees[customer] = customer_data.get(
            "assignees", default_data.get("assignees", [])
        )
        # Get the default assignee for this customer
        default_assignee[customer] = customer_data.get("default_assignee", None)

    return {
        "customer_data": customer_names,
        "work_items": work_items,
        "parent_names": parent_names,
        "devops_tags": DEVOPS_TAGS,
        "contact_persons": contact_persons,
        "assignees": assignees,
        "default_assignee": default_assignee,
    }


@DataPrepRegistry.register("devops_work_item", "Update")
def prep_devops_work_item_update(**kwargs):
    """Prepare data for DevOps work item Update tab."""
    DO = GlobalRegistry.get("DO")
    config_devops_contacts = GlobalRegistry.get("config_devops_contacts")

    # Check if DevOps data is available
    if DO.df is None or DO.df.empty:
        return {}

    # Get unique customer names from DevOps data
    customer_names = helpers.get_unique_list(DO.df, "customer_name")
    work_items = {}

    for customer in customer_names:
        filtered = helpers.filter_df(DO.df, {"customer_name": customer})
        work_items[customer] = [row["display_name"] for _, row in filtered.iterrows()]

    # Prepare customer-specific assignees for Update tab
    assignees = {}
    for customer in customer_names:
        # Get customer-specific data from config
        customer_data = config_devops_contacts.get("customers", {}).get(customer, {})
        default_data = config_devops_contacts.get("default", {})

        # Use customer-specific assignees, or fall back to defaults
        assignees[customer] = customer_data.get(
            "assignees", default_data.get("assignees", [])
        )

    return {
        "customer_data": customer_names,
        "work_items": work_items,
        "assignees": assignees,
    }


# ============================================================================
# Main UI Build Function
# ============================================================================


def ui_add_data():
    """Main UI for adding and managing data entities."""
    # Get global instances from registry
    AD = GlobalRegistry.get("AD")
    DO = GlobalRegistry.get("DO")
    LOG = GlobalRegistry.get("LOG")

    # Get configs from registry
    config_ui = GlobalRegistry.get("config_ui")
    MAIN_DB = GlobalRegistry.get("MAIN_DB")

    # Refresh data on load
    asyncio.run(AD.refresh())

    # Create DevOps handlers instance
    devops_handlers = DevOpsWorkItemHandlers(DO, LOG)

    # ========================================================================
    # Helper Functions
    # ========================================================================

    # Store builders for cross-entity refresh (all entities share AD.df data)
    entity_builders = {}

    def refresh_all_entity_forms():
        """Rebuild all entity forms after AD.df is refreshed."""
        # Rebuild customer forms
        if "customer" in entity_builders:
            builder, tab_types, container_dict = entity_builders["customer"]
            for tab_type in tab_types:
                builder.build_form(
                    tab_type=tab_type,
                    container_dict=container_dict,
                    on_success_callback=on_ad_refresh,
                )

        # Rebuild project forms
        if "project" in entity_builders:
            builder, tab_types, container_dict = entity_builders["project"]
            for tab_type in tab_types:
                builder.build_form(
                    tab_type=tab_type,
                    container_dict=container_dict,
                    on_success_callback=on_ad_refresh,
                )

        # Rebuild bonus forms
        if "bonus" in entity_builders:
            builder, tab_types, container_dict = entity_builders["bonus"]
            for tab_type in tab_types:
                builder.build_form(
                    tab_type=tab_type,
                    container_dict=container_dict,
                    on_success_callback=on_ad_refresh,
                )

    async def on_ad_refresh():
        """Refresh AD data and rebuild all entity forms."""
        await AD.refresh()
        refresh_all_entity_forms()

    def build_entity_tabs(entity_name: str, tab_types: list[str], container_dict: dict):
        """Build tabs for an entity using EntityFormBuilder."""
        builder = EntityFormBuilder(entity_name, config_ui)

        # Store builder for cross-entity refresh
        entity_builders[entity_name] = (builder, tab_types, container_dict)

        with ui.tabs().props("inline-label align=left").classes("w-full") as tabs:
            for tab_type in tab_types:
                ui.tab(tab_type)

        with ui.tab_panels(tabs, value=tab_types[0]).classes("w-full"):
            for tab_type in tab_types:
                with ui.tab_panel(tab_type):
                    # Use lambda with default argument to capture tab_type correctly
                    # This defers form building until the tab panel is actually created
                    (
                        lambda current_tab_type: builder.build_form(
                            tab_type=current_tab_type,
                            container_dict=container_dict,
                            on_success_callback=on_ad_refresh,
                        )
                    )(tab_type)

    def build_work_item_tabs(container_dict: dict):
        """Build DevOps work item tabs with custom handlers."""
        builder = EntityFormBuilder("devops_work_item", config_ui)

        # Create render functions dictionary for markdown preview
        render_functions = {"render_and_sanitize": helpers.render_and_sanitize_markdown}

        # Create refresh callback that reloads DevOps data AND rebuilds forms
        async def on_success_refresh():
            await DO.update_devops(incremental=True)
            await DO.load_df()
            # Rebuild both Add and Update forms
            build_add_form()
            build_update_form()

        def build_add_form():
            """Build the Add form."""
            widgets = builder.build_form(
                tab_type="Add",
                container_dict=container_dict,
                custom_handlers={"add_work_item": devops_handlers.add_work_item},
                on_success_callback=on_success_refresh,
                render_functions=render_functions,
            )
            # Set up special Add tab event handlers
            devops_handlers.setup_add_tab_handlers(widgets)
            return widgets

        def build_update_form():
            """Build the Update form."""
            widgets = builder.build_form(
                tab_type="Update",
                container_dict=container_dict,
                custom_handlers={
                    "update_work_item": devops_handlers.update_work_item,
                    "update_work_item_description": devops_handlers.update_work_item_description,
                },
                on_success_callback=on_success_refresh,
                render_functions=render_functions,
            )
            # Set up special Update tab event handlers
            devops_handlers.setup_update_tab_handlers(widgets)
            return widgets

        with ui.tabs().props("inline-label align=left").classes("w-full") as tabs:
            ui.tab("Add")
            ui.tab("Update")

        with ui.tab_panels(tabs, value="Add").classes("w-full"):
            # Add tab with custom handler and event setup
            with ui.tab_panel("Add"):
                build_add_form()

            # Update tab with custom handlers and event setup
            with ui.tab_panel("Update"):
                build_update_form()

    # ========================================================================
    # Main UI Layout
    # ========================================================================

    with ui.column().classes("w-full gap-4"):
        ui.label("Add Data").classes("text-2xl font-bold")

        # Use splitter for vertical tabs layout (tabs on left, content on right)
        with ui.splitter(value=20).classes("w-full h-full") as splitter:
            # Left side: Vertical tabs
            with splitter.before:
                with ui.tabs().props("vertical").classes("w-full") as tabs_vertical:
                    ui.tab("customer", label="Customer", icon="business")
                    ui.tab("project", label="Project", icon="work")
                    ui.tab("devops", label="DevOps", icon="cloud")
                    ui.tab("bonus", label="Bonus", icon="card_giftcard")
                    ui.tab("database", label="Database", icon="storage")

            # Right side: Tab content
            with splitter.after:
                with (
                    ui.tab_panels(tabs_vertical, value="customer")
                    .props("vertical")
                    .classes("w-full h-full")
                ):
                    # Customer tab panel - use separate container dict
                    with ui.tab_panel("customer"):
                        build_entity_tabs(
                            "customer", ["Add", "Update", "Disable", "Reenable"], {}
                        )

                    # Project tab panel - use separate container dict
                    with ui.tab_panel("project"):
                        build_entity_tabs(
                            "project", ["Add", "Update", "Disable", "Reenable"], {}
                        )

                    # DevOps tab panel - use separate container dict
                    with ui.tab_panel("devops"):
                        build_work_item_tabs({})

                    # Bonus tab panel - use separate container dict
                    with ui.tab_panel("bonus"):
                        build_entity_tabs("bonus", ["Add"], {})

                    # Database tab panel
                    with ui.tab_panel("database"):
                        with (
                            ui.tabs()
                            .props("inline-label align=left")
                            .classes("w-full") as db_tabs
                        ):
                            ui.tab("compare", label="Compare")
                            ui.tab("update", label="Update")

                        with ui.tab_panels(db_tabs, value="compare").classes("w-full"):
                            with ui.tab_panel("compare"):
                                build_database_compare_tab(MAIN_DB)

                            with ui.tab_panel("update"):
                                build_database_update_tab()
