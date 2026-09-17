"""
Shared DevOps form rendering for board dialogs.

This module decouples DevOps add/update UI from add_data page so the
board can own the full DevOps workflow.
"""

import asyncio
import copy
import mimetypes
import re as _re
import time
import uuid

from nicegui import ui, app
from fastapi import UploadFile, File, Request, Response

from .. import helpers
from ..ui.dynamic_widgets import WIDGET_CLASSES
from ..ui.work_item_handlers import WorkItemHandlers


# Images inserted on the ADD form for item-scoped attachment stores (Jira):
# the item doesn't exist yet, so the bytes are STAGED here, previewed via
# /staged_image/<token>, and uploaded + swapped for the real attachment URL
# right after the item is created (see WorkItemHandlers.add_work_item).
_STAGED_IMAGES: dict = {}  # token -> (filename, bytes, monotonic timestamp)
_STAGED_URL_RE = _re.compile(r"/staged_image/([0-9a-f]{32})")


def _prune_staged(max_age: float = 3600.0) -> None:
    now = time.monotonic()
    for token in [
        t for t, v in _STAGED_IMAGES.items() if now - v[2] > max_age
    ]:
        _STAGED_IMAGES.pop(token, None)


def stage_image(file_name: str, content: bytes) -> str:
    """Hold image bytes until the work item exists; returns the preview URL."""
    _prune_staged()
    token = uuid.uuid4().hex
    _STAGED_IMAGES[token] = (file_name or "image.png", content, time.monotonic())
    return f"/staged_image/{token}"


def take_staged_images(markdown_text: str) -> list:
    """[(url_in_text, filename, bytes)] for staged refs in the text — the
    entries are CONSUMED, so call only when the upload is about to happen."""
    out = []
    for token in _STAGED_URL_RE.findall(markdown_text or ""):
        item = _STAGED_IMAGES.pop(token, None)
        if item:
            out.append((f"/staged_image/{token}", item[0], item[1]))
    return out


def strip_staged_image_lines(markdown_text: str) -> str:
    """The text minus staged-image lines — the initial create must not send
    the temporary relative URLs to the tracker."""
    return _re.sub(
        r"^\s*!\[[^\]]*\]\(/staged_image/[0-9a-f]{32}\)\s*$",
        "",
        markdown_text or "",
        flags=_re.M,
    )


@app.get("/staged_image/{token}")
async def staged_image(token: str):
    item = _STAGED_IMAGES.get(token)
    if not item:
        return Response(status_code=404)
    media_type = mimetypes.guess_type(item[0])[0] or "image/png"
    return Response(content=item[1], media_type=media_type,
                    headers={"Cache-Control": "private, max-age=3600"})


@app.post("/upload_devops_image")
async def upload_devops_image(request: Request, file: UploadFile = File(...)):
    """Upload a pasted/picked image as a DevOps attachment for a customer and
    return {path: url} so it can be embedded in a work-item description."""
    # Use the process-wide engine directly: this is a plain HTTP endpoint with no
    # NiceGUI client context, so AppCore.get_or_initialize() would fail.
    from ..core.app import get_global_tracker_engine

    form = await request.form()
    customer = form.get("customer")
    if not customer:
        return {"error": "Missing customer"}
    # Item-scoped stores (Jira) attach to the work item being edited.
    work_item_id = form.get("work_item_id")
    content = await file.read()
    # Add-form paste for an item-scoped store: no item exists yet — stage
    # the bytes; add_work_item uploads them right after the create.
    if form.get("stage") and not work_item_id:
        return {"path": stage_image(file.filename or "paste.png", content)}
    engine = get_global_tracker_engine()
    if engine is None:
        return {"error": "No DevOps connection"}
    url = await asyncio.to_thread(
        engine.upload_attachment,
        customer,
        file.filename or "paste.png",
        content,
        int(work_item_id) if work_item_id else None,
    )
    return {"path": url} if url else {"error": "Upload failed"}


@app.get("/devops_attachment")
async def devops_attachment(url: str):
    """Proxy a DevOps work-item attachment with the matching customer's PAT, so
    images embedded in a description render in the WorkTimer preview (the browser
    can't authenticate to dev.azure.com directly)."""
    from ..core.app import get_global_tracker_engine

    engine = get_global_tracker_engine()
    manager = getattr(engine, "manager", None) if engine else None
    if manager is None:
        return Response(status_code=404)
    result = await asyncio.to_thread(manager.fetch_attachment, url)
    if not result:
        return Response(status_code=404)
    content, content_type = result
    return Response(
        content=content,
        media_type=content_type or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=3600"},
    )


def _with_loading(button, handler):
    """Wrap an async click handler so `button` shows Quasar's loading spinner
    (text → spinner, further clicks ignored) while it runs — tracker writes
    are network calls that can take a couple of seconds."""

    async def _run():
        button.props("loading")
        try:
            await handler()
        finally:
            try:
                button.props(remove="loading")
            except Exception:
                pass  # dialog already closed and the button deleted

    return _run


_DIALOG_CARD_STYLE = (
    "margin: 2rem auto; width: calc(100% - 4rem); max-width: 980px;"
    "max-height: calc(100vh - 4rem); overflow-y: auto;"
)
_PRIORITY_COLORS = {1: "red-5", 2: "orange-4", 3: "blue-4", 4: "grey-4"}
_PRIORITY_LABELS = {1: "Critical", 2: "High", 3: "Medium", 4: "Low"}


async def open_work_item_dialog(
    core,
    row: dict,
    on_success=None,
    priority_colors: dict | None = None,
    priority_labels: dict | None = None,
):
    """Open the full DevOps work-item update dialog for a single item.

    Shared by the board (card click) and the hierarchy (node click). Shows the
    editable fields, the description and the comments thread, plus an
    "Open in DevOps" link. `on_success` (async, optional) runs after a save.
    """
    priority_colors = priority_colors or _PRIORITY_COLORS
    priority_labels = priority_labels or _PRIORITY_LABELS

    item_id = int(row.get("id", 0))
    item_type = str(row.get("type", "User Story"))
    title = str(row.get("title", ""))
    customer = str(row.get("customer_name", ""))
    priority_val = row.get("priority")

    # Customer indicator colour (fills the header badge when set).
    cust_color = None
    try:
        _cc = await core.query_engine.query_db(
            "SELECT color FROM customers WHERE customer_name = ? AND is_current = 1 LIMIT 1",
            params=(customer,),
        )
        if not _cc.empty and _cc.iloc[0]["color"]:
            cust_color = str(_cc.iloc[0]["color"])
    except Exception:
        cust_color = None
    display_name = f"{item_type}: {item_id} - {title}"
    update_cfg = core.ui_config.get("board_devops_forms", {}).get("update", {})
    # The customer's tracker name/capabilities drive labels and feature gating
    # (e.g. no image upload for a tracker without attachment support).
    tracker_label = core.tracker_engine.provider_label(customer)
    tracker_caps = core.tracker_engine.capabilities(customer)

    def _open_in_devops():
        manager = getattr(core.tracker_engine, "manager", None)
        url = manager.get_work_item_url(customer, item_id) if manager else None
        if url:
            ui.navigate.to(url, new_tab=True)
        else:
            ui.notify(f"Could not build the {tracker_label} URL", type="warning")

    with ui.dialog().props("maximized") as dlg:
        with ui.card().style(_DIALOG_CARD_STYLE).props("flat bordered"):
            form_actions: dict = {"submit": None}
            dirty_state: dict = {"is_dirty": False, "programmatic": True}

            def _mark_dirty(_e=None):
                if not dirty_state["programmatic"]:
                    dirty_state["is_dirty"] = True

            def _confirm_discard_or_close():
                if not dirty_state["is_dirty"]:
                    dlg.close()
                    return
                with ui.dialog() as confirm_dlg, ui.card().classes("w-96"):
                    ui.label("Discard unsaved changes?").classes("text-sm font-semibold")
                    ui.label("Your edits in this work item will be lost.").classes(
                        "text-xs text-grey-5"
                    )
                    with ui.row().classes("w-full justify-end gap-2 mt-2"):
                        ui.button("Keep editing", on_click=confirm_dlg.close).props("flat")

                        def _discard():
                            confirm_dlg.close()
                            dlg.close()

                        ui.button("Discard", on_click=_discard).props("color=negative")
                confirm_dlg.open()

            async def _submit_from_header():
                submit_fn = form_actions.get("submit")
                if submit_fn:
                    await submit_fn()

            # ── header ────────────────────────────────────────────────────────
            p_color = priority_colors.get(priority_val, "grey-4")
            p_label = priority_labels.get(priority_val, "")
            with ui.row().classes("items-center gap-2 no-wrap w-full").style(
                "padding: 0.6rem 0.8rem; flex-shrink: 0;"
            ):
                if priority_val:
                    ui.icon("circle", size="12px").classes(
                        f"text-{p_color} shrink-0"
                    ).tooltip(f"Priority: {p_label}")
                ui.label(f"#{item_id}").classes("text-grey-5 text-xs shrink-0")
                ui.label("·").classes("text-grey-5 text-xs shrink-0")
                ui.label(item_type).classes("text-grey-5 text-xs shrink-0")
                ui.label(title).classes("text-sm font-semibold flex-1").style(
                    "overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
                )
                _cust_badge = ui.badge(customer).props("rounded").classes("text-xs shrink-0")
                if cust_color:
                    _cust_badge.style(f"background:{cust_color}; color:#fff;")
                else:
                    _cust_badge.props("color=primary outline")
                ui.space()
                ui.button(icon="open_in_new", on_click=_open_in_devops).props(
                    "flat dense color=primary"
                ).tooltip(f"Open in {tracker_label}")
                _update_btn = ui.button("Update", icon="save").props("dense color=primary")
                _update_btn.on("click", _with_loading(_update_btn, _submit_from_header))
                ui.button("Cancel", icon="close", on_click=_confirm_discard_or_close).props(
                    "flat dense color=grey-6"
                )
            ui.separator()

            loading_box = ui.column().classes("w-full gap-2").style("padding: 0.75rem;")
            with loading_box:
                ui.skeleton("text", width="35%")
                for _ in range(3):
                    ui.skeleton("rect", width="100%", height="52px")
                ui.skeleton("rect", width="100%", height="220px")

            dlg.open()
            await asyncio.sleep(0)

            async def _on_update_success():
                dlg.close()
                if on_success:
                    await on_success()

            # try/finally: any failure while building the form (a provider
            # missing an optional API, a network hiccup mid-load) must still
            # clear the skeletons — otherwise the dialog "loads forever".
            try:
                result = await render_devops_form(
                    core, "update", update_cfg,
                    on_success=_on_update_success,
                    hidden_field_names={"customer_name", "work_item", "current_column", "board_column"},
                    show_internal_header=False,
                )

                _, widgets, load_fn, submit_fn = result if result else (None, {}, None, None)
                form_actions["submit"] = submit_fn

                if widgets:
                    if "customer_name" in widgets:
                        widgets["customer_name"].widget.value = customer
                        widgets["customer_name"].widget.update()
                    if "work_item" in widgets:
                        await widgets["work_item"].refresh()
                        widgets["work_item"].widget.value = display_name
                        widgets["work_item"].widget.update()
                    if load_fn:
                        try:
                            await load_fn(None)
                        except Exception as e:
                            core.logger.error(
                                f"Work-item detail load failed for #{item_id}: {e}"
                            )
                            ui.notify(
                                "Could not load all work-item details",
                                type="warning",
                            )

                    dirty_state["programmatic"] = False
                    for field_name in ("state", "assigned_to", "priority", "description_editor"):
                        w = widgets.get(field_name)
                        if w:
                            w.on_value_change(_mark_dirty)

                    # Images: upload as tracker attachments (button + paste), now
                    # that we know the customer — only for trackers that support
                    # attachments (Jira v1 doesn't; the toolbar stays clean).
                    desc = widgets.get("description_editor")
                    if (
                        desc is not None and customer
                        and tracker_caps.attachments
                        and hasattr(desc, "enable_image_upload")
                    ):

                        async def _devops_image_uploader(
                            name, content, _cust=customer, _wid=item_id
                        ):
                            return await asyncio.to_thread(
                                core.tracker_engine.upload_attachment,
                                _cust, name, content, _wid,
                            )

                        desc.enable_image_upload(
                            _devops_image_uploader,
                            paste_endpoint="/upload_devops_image",
                            paste_fields={
                                "customer": customer,
                                "work_item_id": str(item_id),
                            },
                        )
            except Exception as e:
                core.logger.error(
                    f"Work-item dialog failed to build for #{item_id}: {e}"
                )
                ui.notify("Could not load the work item", type="negative")
                dlg.close()
            finally:
                loading_box.clear()

    # Returned so long-lived callers (the command palette's find-mode) can
    # dispose of the dialog on close; page-scoped callers may ignore it.
    return dlg


async def open_add_work_item_dialog(
    core,
    preset_customer: str | None = None,
    preset_type: str | None = None,
    preset_parent: str | None = None,
    on_success=None,
):
    """Open the full DevOps add form in a dialog, page-independently.

    Used by the board (＋ button), the hierarchy view (＋ with `preset_parent`
    pre-selecting the focused node as parent) and the command palette ("Add
    Epic/Feature/User Story" over whatever page is open). `on_success` (async,
    optional) runs after a successful save. Returns the dialog so long-lived
    callers can dispose of it on close."""
    add_cfg = core.ui_config.get("board_devops_forms", {}).get("add", {})
    muted = core.theme.get("muted")

    with ui.dialog().props("maximized") as dlg:
        with ui.card().style(_DIALOG_CARD_STYLE).props("flat bordered"):
            form_actions: dict = {"submit": None}

            async def _submit_from_header():
                submit_fn = form_actions.get("submit")
                if submit_fn:
                    await submit_fn()

            # Match the update dialog look with a top context bar.
            with ui.row().classes("items-center gap-2 no-wrap w-full").style(
                "padding: 0.6rem 0.8rem; flex-shrink: 0;"
            ):
                ui.icon("add_circle", size="16px").classes("text-primary shrink-0")
                ui.label("New Work Item").classes(
                    f"text-{muted} text-xs uppercase tracking-wide shrink-0"
                )
                ui.label("·").classes(f"text-{muted} text-xs shrink-0")
                type_label = ui.label(preset_type or "User Story").classes(
                    f"text-{muted} text-xs shrink-0"
                )
                customer_label = ui.label(preset_customer or "").classes(
                    "text-sm font-semibold flex-1"
                ).style("overflow:hidden; text-overflow:ellipsis; white-space:nowrap;")
                ui.space()
                _add_btn = ui.button("Add", icon="save").props("dense color=primary")
                _add_btn.on("click", _with_loading(_add_btn, _submit_from_header))
                ui.button("Cancel", icon="close", on_click=dlg.close).props(
                    "flat dense color=grey-6"
                )
            ui.separator()

            async def _on_add_success():
                dlg.close()
                if on_success:
                    await on_success()

            result = await render_devops_form(
                core, "add", add_cfg,
                on_success=_on_add_success,
                show_internal_header=False,
            )

            _, widgets, load_fn, submit_fn = result if result else (None, {}, None, None)
            form_actions["submit"] = submit_fn

            if widgets:
                if preset_customer and "customer_name" in widgets:
                    widgets["customer_name"].widget.value = preset_customer
                    widgets["customer_name"].widget.update()
                # Only force the type for an explicit preset (board lane add);
                # otherwise the config default applies and the snap below
                # corrects it per tracker.
                if preset_type and "work_item_type" in widgets:
                    widgets["work_item_type"].widget.value = preset_type
                    widgets["work_item_type"].widget.update()

                def _sync_add_header(_e=None):
                    if "work_item_type" in widgets:
                        type_label.set_text(
                            str(widgets["work_item_type"].widget.value or "")
                        )
                    if "customer_name" in widgets:
                        customer_label.set_text(
                            str(widgets["customer_name"].widget.value or "")
                        )

                def _snap_type_to_customer(_e=None):
                    """Keep the type valid for the selected customer's tracker
                    (mirrors the board's customer-switch snap): a pick that's
                    valid for the new tracker survives; an invalid one becomes
                    the tracker's preferred level."""
                    tw = widgets.get("work_item_type")
                    cw = widgets.get("customer_name")
                    if tw is None or cw is None or core.tracker_engine is None:
                        return
                    cust_now = cw.widget.value
                    if not cust_now:
                        return
                    types = core.tracker_engine.type_hierarchy(cust_now)
                    if tw.widget.value not in types:
                        tw.widget.value = core.tracker_engine.preferred_type(cust_now)
                        tw.widget.update()
                        _sync_add_header()
                    # Same for State: Azure's default "New" means nothing to a
                    # Jira workflow — snap to the tracker's first state.
                    sw = widgets.get("state")
                    if sw is not None:
                        states = core.tracker_engine.state_options(cust_now)
                        if states and sw.widget.value not in states:
                            sw.widget.value = states[0]
                            sw.widget.update()
                    # State IS the board column for some trackers (Jira) —
                    # hide the redundant Initial Board Column input there.
                    bc = widgets.get("board_column")
                    if bc is not None:
                        caps = core.tracker_engine.capabilities(cust_now)
                        bc.widget.set_visibility(caps.distinct_board_column)
                        if not caps.distinct_board_column and bc.widget.value:
                            bc.widget.value = None
                            bc.widget.update()

                def _apply_tracker_defaults(_e=None):
                    """Configured per-tracker/per-type prefills (Settings →
                    Trackers): state / priority / column / source / contact.
                    Runs as a task so parent-dependent dropdowns can load
                    their options before values are applied; re-applied when
                    the customer OR the work-item type changes."""

                    async def _run():
                        cw = widgets.get("customer_name")
                        cust_now = cw.widget.value if cw else None
                        if not cust_now or core.tracker_engine is None:
                            return
                        from ..tracker_defaults import (
                            DEFAULT_FIELDS,
                            defaults_for,
                            load_tracker_defaults,
                        )

                        tracker_map = await core.query_engine.function_db(
                            "get_customer_tracker_names"
                        )
                        tw = widgets.get("work_item_type")
                        wtype = tw.widget.value if tw else None
                        defaults = defaults_for(
                            load_tracker_defaults(
                                core.config_loader.config_folder
                            ),
                            tracker_map.get(cust_now, ""),
                            wtype,
                        )
                        if not defaults:
                            return
                        caps = core.tracker_engine.capabilities(cust_now)
                        for fname in DEFAULT_FIELDS:
                            val = defaults.get(fname)
                            w = widgets.get(fname)
                            if w is None or val in (None, ""):
                                continue
                            if (
                                fname == "board_column"
                                and not caps.distinct_board_column
                            ):
                                continue
                            try:
                                if getattr(w, "parent", None) is not None:
                                    await w.refresh()  # options first
                                # Selects may stringify numeric options —
                                # route the value through the same coercion
                                # (a raw int priority never matched).
                                coerce = getattr(
                                    w, "_coerce_value_for_select", None
                                )
                                w.widget.value = (
                                    coerce(val) if callable(coerce) else val
                                )
                                w.widget.update()
                            except Exception:
                                pass  # a default must never break the form

                    asyncio.create_task(_run())

                if "work_item_type" in widgets:
                    widgets["work_item_type"].on_value_change(_sync_add_header)
                    # Per-type defaults follow the level selection.
                    widgets["work_item_type"].on_value_change(
                        _apply_tracker_defaults
                    )
                if "customer_name" in widgets:
                    widgets["customer_name"].on_value_change(_sync_add_header)
                    widgets["customer_name"].on_value_change(_snap_type_to_customer)
                    widgets["customer_name"].on_value_change(_apply_tracker_defaults)
                _sync_add_header()

                # The type is a parent-dependent select: refresh loads its
                # options for the preset customer (a value set against empty
                # options doesn't stick), then the preset is applied on top.
                if "work_item_type" in widgets:
                    try:
                        await widgets["work_item_type"].refresh()
                    except Exception:
                        pass
                    if preset_type:
                        widgets["work_item_type"].widget.value = preset_type
                        widgets["work_item_type"].widget.update()
                # The OTHER parent-dependent selects (state, assigned to,
                # contact person, parent) have the same blind spot: the
                # programmatic customer set fires no browser event, so until
                # something refreshed them they showed their static fallback
                # options (every tracker's values mixed). Refresh them all
                # against the current customer once, right here. A blank
                # customer is safe — the parent-keyed-options guard leaves
                # the widget untouched then.
                for _fname, _w in widgets.items():
                    if _fname != "work_item_type" and getattr(_w, "parent", None) is not None:
                        try:
                            await _w.refresh()
                        except Exception:
                            pass
                _snap_type_to_customer()
                # Board columns are per (customer, work-item TYPE) — in Azure
                # every backlog level has its own board — so the loader may
                # only run once the type above is FINAL. The programmatic sets
                # fire no "update:model-value" browser event, hence the direct
                # call; calling it any earlier loaded the default type's
                # columns (a Feature form showed the Story board's columns).
                if load_fn:
                    await load_fn()
                _sync_add_header()
                _apply_tracker_defaults()

                # Pre-parent the new item (hierarchy ＋ on a focused node).
                # Same pattern as the update dialog's work_item pre-fill:
                # refresh loads the options for the current customer, then
                # the value is set on top of them.
                if preset_parent and "parent_name" in widgets:
                    await widgets["parent_name"].refresh()
                    widgets["parent_name"].widget.value = preset_parent
                    widgets["parent_name"].widget.update()

                # Image insert (button + paste) on the Description editor —
                # parity with the update dialog. Here the customer is chosen
                # in the form and can change, so resolve it at upload time and
                # keep the paste target in sync when it changes.
                desc = widgets.get("description_editor")
                cust_w = widgets.get("customer_name")
                if (
                    desc is not None and cust_w is not None
                    and hasattr(desc, "enable_image_upload")
                    and core.tracker_engine is not None
                ):
                    async def _add_image_uploader(name, content):
                        cust_now = cust_w.widget.value
                        if not cust_now:
                            # False = refused-and-explained: the button's
                            # generic "upload failed" toast is suppressed.
                            ui.notify("Pick a customer first", type="warning")
                            return False
                        # Fallback gate — the button is hidden for trackers
                        # without attachments, but the selection can race.
                        caps = core.tracker_engine.capabilities(cust_now)
                        if not caps.attachments:
                            ui.notify(
                                f"{core.tracker_engine.provider_label(cust_now)} "
                                "doesn't support image attachments yet",
                                type="warning",
                            )
                            return False
                        if caps.attachments_require_item:
                            # Item-scoped store (Jira): no item yet — stage
                            # now, upload right after the create.
                            return stage_image(name, content)
                        return await asyncio.to_thread(
                            core.tracker_engine.upload_attachment,
                            cust_now, name, content,
                        )

                    desc.enable_image_upload(
                        _add_image_uploader,
                        paste_endpoint="/upload_devops_image",
                        paste_fields={"customer": cust_w.widget.value or ""},
                    )

                    def _sync_paste_customer(_e=None):
                        cust_now = cust_w.widget.value
                        caps = core.tracker_engine.capabilities(cust_now)
                        paste_fields = {"customer": cust_now or ""}
                        if caps.attachments_require_item:
                            # Pastes are staged too — see /upload_devops_image.
                            paste_fields["stage"] = "1"
                        desc.update_paste_fields(
                            "/upload_devops_image", paste_fields
                        )
                        # Hide the Insert-image button only for trackers with
                        # no attachment support at all (item-scoped stores
                        # stage instead). Visible while no customer is chosen.
                        if hasattr(desc, "set_image_upload_visible"):
                            desc.set_image_upload_visible(
                                not cust_now or caps.attachments
                            )

                    cust_w.on_value_change(_sync_paste_customer)
                    _sync_paste_customer()

    dlg.open()
    return dlg


def _render_comment(comment: dict) -> None:
    """Render one Azure DevOps comment (author/date header + body)."""
    with ui.card().props("flat bordered").classes("w-full"):
        ui.label(
            f"{comment.get('author') or 'Unknown'} · {str(comment.get('date') or '')[:16].replace('T', ' ')}"
        ).classes("text-xs text-grey-5")
        text = comment.get("text") or ""
        # ADO comments are usually HTML; render as sanitized markdown either way.
        md = helpers.convert_html_to_markdown(text) if "<" in text else text
        ui.html(helpers.render_and_sanitize_markdown(md)).classes("text-sm w-full")


async def _load_comments_into(core, widgets: dict, container) -> None:
    """Fetch the selected work item's comments and render them into `container`."""
    wid_widget = widgets.get("work_item")
    cust_widget = widgets.get("customer_name")
    container.clear()
    if not wid_widget or not cust_widget:
        return
    work_item_id = helpers.extract_devops_id(wid_widget.value)
    customer = cust_widget.value
    if not work_item_id or not customer:
        return
    manager = getattr(core.tracker_engine, "manager", None)
    if not manager:
        return

    with container:
        ui.label("Loading comments…").classes("text-xs text-grey-5")
    ok, data = await asyncio.to_thread(manager.get_comments, customer, work_item_id)
    container.clear()
    with container:
        if not ok:
            ui.label(f"Could not load comments: {data}").classes("text-xs text-negative")
        elif not data:
            ui.label("No comments yet.").classes("text-xs text-grey-5")
        else:
            for comment in data:
                _render_comment(comment)


async def render_devops_form(
    core,
    operation: str,
    form_config: dict,
    on_success=None,
    on_close=None,
    hidden_field_names: set = None,
    show_internal_header: bool = True,
):
    """Render DevOps work item form (shared by add and update)."""
    # Deep-copy: the config dicts are shared process-wide; assign_dynamic_options
    # writes options into the field dicts, which must not leak across clients.
    fields = copy.deepcopy(form_config.get("fields", []))
    action = form_config.get("action", {})

    data_sources = await prepare_devops_data_sources(core, operation)
    helpers.assign_dynamic_options(fields, data_sources=data_sources)

    widgets: dict = {}
    dynamic_widgets: list = []
    parent_map: dict = {}

    async def on_submit():
        required_fields = [
            f.get("name") or f.get("field_id")
            for f in fields
            if not f.get("optional", False)
        ]
        if not helpers.check_input(widgets, required_fields):
            return

        if (
            not core.tracker_engine
            or not hasattr(core.tracker_engine, "manager")
            or not core.tracker_engine.manager
        ):
            ui.notify("DevOps not configured - check PAT token / org URL", type="negative")
            return

        try:
            item_handlers = WorkItemHandlers(core.tracker_engine, core.logger)
            if operation == "add":
                wid_title = widgets.get("work_item_title")
                success, message = await item_handlers.add_work_item(widgets)
                success_msg = f"Work item created: {wid_title.value if wid_title else ''}"
            else:
                success, message = await item_handlers.update_work_item(widgets)
                success_msg = "Work item updated"

            if success:
                ui.notify(success_msg, type="positive")
                core.logger.info(message)
                await core.tracker_engine.refresh_tracker_data(incremental=True)
                core.event_bus.emit("ui_refresh_requested")
                if on_success:
                    await on_success()
            else:
                ui.notify(f"Failed: {message}", type="negative")
                core.logger.error(message)
        except Exception as e:
            core.logger.error(f"Error in DevOps {operation}: {e}")
            ui.notify(f"Error: {e}", type="negative")

    with (
        ui.card()
        .classes("overflow-y-auto w-full rounded-lg")
        .style("max-height: 82vh; padding: 1rem; box-sizing: border-box;")
        .props("flat")
    ):
        if show_internal_header:
            title = action.get("title", f"{operation.capitalize()} DevOps Work Item")
            with ui.row().classes("w-full items-center gap-2 mt-4"):
                ui.label(title).classes(helpers.UI_STYLES.get_layout_classes("title"))
                ui.space()
                _submit_btn = ui.button(
                    action.get("button_name", "Submit"), icon="save"
                ).props("color=primary")
                _submit_btn.on("click", _with_loading(_submit_btn, on_submit))
                if on_close:
                    ui.button(icon="close", on_click=on_close).props("flat dense round color=grey-6").tooltip("Close")

        if not data_sources.get("customer_data"):
            ui.label("No tracker data available. Please configure a tracker connection first.").classes("text-warning")
            return None, {}, None, None

        rows_layout = form_config.get("rows", []) or [
            [f.get("name") or f.get("field_id")] for f in fields
        ]

        async def devops_data_fetcher(source_key, parent_val=None):
            if source_key == "devops_tags":
                return core.devops_tags_config.devops_tags or []
            if source_key not in data_sources:
                return [] if parent_val is not None else ""
            data = data_sources[source_key]
            if source_key == "parent_names" and isinstance(data, dict) and parent_val:
                customer_dict = data.get(parent_val, {})
                if isinstance(customer_dict, dict):
                    return list({
                        item
                        for parent_list in customer_dict.values()
                        if isinstance(parent_list, list)
                        for item in parent_list
                    })
                return customer_dict if isinstance(customer_dict, list) else []
            if parent_val and isinstance(data, dict):
                return data.get(parent_val, [])
            elif isinstance(data, list):
                return data
            elif isinstance(data, dict):
                return data
            return [] if parent_val is not None else ""

        field_name_to_type = {f.get("name") or f.get("field_id"): f.get("type") for f in fields}
        fields_by_name = {f.get("name") or f.get("field_id"): f for f in fields}
        hidden = set(hidden_field_names or [])
        has_wide_layout = any(
            helpers.UI_STYLES.is_wide_widget(field_name_to_type.get(fn))
            for row in rows_layout
            for fn in row
        )

        if hidden:
            with ui.element("div").style("display: none;"):
                for field in fields:
                    fname = field.get("name") or field.get("field_id")
                    if fname not in hidden or fname in widgets:
                        continue
                    widget_class = WIDGET_CLASSES.get(field.get("type", "input"))
                    if not widget_class:
                        continue
                    parent_field = field.get("parent")
                    dw = widget_class(
                        name=fname,
                        data_fetcher=devops_data_fetcher,
                        options_source=field.get("options_source", ""),
                        parent=parent_map.get(parent_field) if parent_field else None,
                        label=field.get("label", fname),
                        initial_value=field.get("default"),
                        field_config=field,
                    )
                    widgets[fname] = dw
                    parent_map[fname] = dw
                    dynamic_widgets.append(dw)

        with ui.column().classes(helpers.UI_STYLES.get_layout_classes("form_column")):
            for row in rows_layout:
                row_field_configs = [fields_by_name[fn] for fn in row if fn in fields_by_name and fn not in hidden]
                if not row_field_configs:
                    continue

                is_single_field = len(row_field_configs) == 1
                default_size = "full" if (has_wide_layout or is_single_field) else "standard"

                with ui.row().classes(helpers.UI_STYLES.get_layout_classes("form_row")):
                    for field in row_field_configs:
                        field_name = field.get("name") or field.get("field_id")
                        field_type = field.get("type", "input")
                        parent_field = field.get("parent")

                        widget_class = WIDGET_CLASSES.get(field_type)
                        if not widget_class:
                            core.logger.warning(f"Unknown field type '{field_type}', skipping {field_name}")
                            continue

                        dw = widget_class(
                            name=field_name,
                            data_fetcher=devops_data_fetcher,
                            options_source=field.get("options_source", ""),
                            parent=parent_map.get(parent_field) if parent_field else None,
                            label=field.get("label", field_name),
                            initial_value=field.get("default"),
                            field_config=field,
                        )
                        dw.widget.classes(helpers.UI_STYLES.get_widget_width(field.get("size", default_size)))
                        widgets[field_name] = dw
                        parent_map[field_name] = dw
                        dynamic_widgets.append(dw)

        helpers.setup_template_handling(widgets)
        _setup_conditional_visibility(widgets, fields_by_name, hidden)
        item_handlers_setup = WorkItemHandlers(core.tracker_engine, core.logger)
        if operation == "add":
            load_fn = item_handlers_setup.setup_add_tab_handlers(widgets)
        else:
            load_fn = item_handlers_setup.setup_update_tab_handlers(widgets)

        # Comments panel (update only) — the work item's discussion thread.
        # Shown in the board dialog and the hierarchy dialog alike.
        if operation == "update":
            ui.separator().classes("mt-3")
            ui.label("Comments").classes(
                helpers.UI_STYLES.get_layout_classes("muted_text_xs") + " mt-2"
            )

            # comments_box is created below the input; a holder lets the closures
            # above reference it before it exists.
            _refs: dict = {}

            async def _reload_comments(_e=None):
                box = _refs.get("box")
                if box is not None:
                    await _load_comments_into(core, widgets, box)

            # Add-comment row — on top, above the thread.
            with ui.row().classes("w-full items-end gap-2 mt-1"):
                new_comment = (
                    ui.textarea(placeholder="Add a comment…")
                    .props("outlined dense autogrow")
                    .classes("flex-1")
                )

                async def _post_comment():
                    text = (new_comment.value or "").strip()
                    if not text:
                        return
                    wid_widget = widgets.get("work_item")
                    cust_widget = widgets.get("customer_name")
                    work_item_id = helpers.extract_devops_id(wid_widget.value) if wid_widget else None
                    customer = cust_widget.value if cust_widget else None
                    manager = getattr(core.tracker_engine, "manager", None)
                    if not (work_item_id and customer and manager):
                        return
                    ok, msg = await asyncio.to_thread(
                        manager.save_comment,
                        customer_name=customer,
                        comment=text,
                        git_id=int(work_item_id),
                    )
                    if ok:
                        new_comment.value = ""
                        ui.notify("Comment added", type="positive")
                        await _reload_comments()
                    else:
                        ui.notify(f"Failed to add comment: {msg}", type="negative")

                _send_btn = ui.button(icon="send").props(
                    "dense color=primary"
                ).tooltip("Add comment")
                _send_btn.on("click", _with_loading(_send_btn, _post_comment))

            # Thread — newest first (see get_work_item_comments).
            _refs["box"] = ui.column().classes("w-full gap-2 mt-1")

            work_item_widget = widgets.get("work_item")
            if work_item_widget:
                work_item_widget.on("update:model-value", _reload_comments)

            # Fold comment-loading into load_fn so callers that prefill the work
            # item (the board/hierarchy dialogs) load comments too.
            _inner_load = load_fn

            async def load_fn(_e=None, _base=_inner_load):
                if _base:
                    await _base(_e)
                await _reload_comments(_e)

    async def refresh_all_widgets():
        try:
            for dw in dynamic_widgets:
                await dw.refresh()
        except Exception as e:
            core.logger.error(f"Error refreshing DevOps.{operation} widgets: {e}")

    return refresh_all_widgets, widgets, load_fn, on_submit


def _setup_conditional_visibility(widgets: dict, fields_by_name: dict, hidden: set) -> None:
    """Wire `conditional: true` / `visible_when:` field configs to widget visibility.

    Restores a feature the legacy form factory used to provide: e.g. the DevOps
    add form hides Source/Contact/Parent unless the work item type matches.
    Bound via on_value_change, which also fires on programmatic value sets
    (e.g. the board dialog pre-selecting the work item type).
    """
    conditional = [
        (name, cfg.get("visible_when"))
        for name, cfg in fields_by_name.items()
        if cfg.get("conditional") and cfg.get("visible_when")
        and name in widgets and name not in hidden
    ]
    if not conditional:
        return

    def apply_visibility(_e=None):
        for name, visible_when in conditional:
            visible = True
            for cond_field, cond_values in visible_when.items():
                cond_widget = widgets.get(cond_field)
                value = cond_widget.value if cond_widget is not None else None
                if not value:
                    visible = False
                    break
                if isinstance(cond_values, list):
                    if value not in cond_values:
                        visible = False
                        break
                elif value != cond_values:
                    visible = False
                    break
            widgets[name].widget.set_visibility(visible)

    condition_fields = {cf for _, vw in conditional for cf in vw}
    for cond_field in condition_fields:
        if cond_field in widgets:
            widgets[cond_field].on_value_change(apply_visibility)

    apply_visibility()


async def prepare_devops_data_sources(core, operation: str) -> dict:
    """Prepare data sources for DevOps forms."""
    DO = core.tracker_engine
    data_sources = {}

    try:
        data_sources["devops_tags"] = core.devops_tags_config.devops_tags or []

        if not DO or not hasattr(DO, "df") or DO.df is None or DO.df.empty:
            return data_sources

        customer_names = DO.df["customer_name"].unique().tolist()
        data_sources["customer_data"] = customer_names

        work_items = {}
        parent_names = {}

        for customer in customer_names:
            customer_df = DO.df[DO.df["customer_name"] == customer]
            work_items[customer] = customer_df["display_name"].tolist()

            # Parent options per level from the customer's tracker hierarchy:
            # anything at a strictly higher level qualifies (Azure: User Story
            # under Epic or Feature; Jira: Story under Epic, Sub-task under
            # Epic/Story — the tracker rejects invalid picks with its own msg).
            levels = list(DO.type_hierarchy(customer))
            parent_names[customer] = {
                level: customer_df[customer_df["type"].isin(levels[:i])][
                    "display_name"
                ].tolist()
                for i, level in enumerate(levels)
            }

        data_sources["work_items"] = work_items
        data_sources["parent_names"] = parent_names
        # Per-customer type options, driven by the tracker (Azure:
        # Epic/Feature/User Story; Jira: Epic/Story/Sub-task).
        data_sources["work_item_types"] = {
            c: list(DO.type_hierarchy(c)) for c in customer_names
        }
        # Per-customer state options (Jira: project statuses; may fetch once
        # per provider → keep it off the event loop).
        data_sources["work_item_states"] = await asyncio.to_thread(
            lambda: {c: DO.state_options(c) for c in customer_names}
        )

        try:
            config_devops = core.config_loader.get_raw_dict("devops_contacts")

            contact_persons = {}
            assignees = {}
            default_assignee = {}

            for customer in customer_names:
                customer_data = config_devops.get("customers", {}).get(customer, {})
                default_data = config_devops.get("default", {})

                contact_persons[customer] = customer_data.get(
                    "contacts", default_data.get("contacts", [])
                )
                assignees[customer] = customer_data.get(
                    "assignees", default_data.get("assignees", [])
                )
                default_assignee[customer] = customer_data.get("default_assignee", None)

            data_sources["contact_persons"] = contact_persons
            data_sources["assignees"] = assignees
            data_sources["default_assignee"] = default_assignee

        except Exception as e:
            core.logger.debug(f"DevOps contacts config not available: {e}")

    except Exception as e:
        core.logger.error(f"Error preparing DevOps data sources: {e}")

    return data_sources
