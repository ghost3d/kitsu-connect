"""Browser navigation: Assets / Shots -> asset type or sequence -> entity -> task.

The choices live in session.data (they survive opening a .blend file); rebuild() copies
them into the UI lists on the WindowManager and keeps them consistent.
"""

from . import session, thumbs
from .props import get_state, refresh_file_list

busy = False  # set while rebuild() writes UI properties, so their update callbacks stay quiet

SECTIONS = ("ASSETS", "SHOTS")


def project_rows():
    pid = session.data["project_id"]
    return [r for r in session.data["rows"] if pid == "ALL" or r.project_id == pid]


def group_of(row):
    if session.data["project_id"] == "ALL":
        return f"{row.project_name}: {row.group}"
    return row.group


def _unique(values):
    return list(dict.fromkeys(values))


# Blender needs the enum item list kept alive in Python, or labels turn to garbage.
_group_items = []


def group_items():
    global _group_items
    kind = session.data["kind"]
    rows = [r for r in project_rows() if r.section == kind]
    all_label = "All Asset Types" if kind == "ASSETS" else "All Sequences"
    items = [("ALL", all_label, "Show everything", 'COLLAPSEMENU', 0)]
    for i, g in enumerate(_unique(group_of(r) for r in rows), start=1):
        count = len({r.entity_id for r in rows if group_of(r) == g})
        items.append((g, f"{g}  ({count})", f"Show only {g}", 'FILE_FOLDER', i))
    _group_items = items
    return _group_items


def rebuild(context, task_id=None, keep_kind=False):
    """Refresh groups, entities, tasks and files from the session.

    If `task_id` (or the remembered task) is in the current project, the browser moves to it.
    Unless `keep_kind` is set, an empty Assets or Shots side switches to the other one.
    """
    global busy
    d, state = session.data, get_state(context)
    rows = project_rows()
    task_id = task_id or d["selected_task"]

    target = next((r for r in rows if r.task_id == task_id), None)
    if target:
        d["kind"] = target.section
        if d["group"] not in ("ALL", group_of(target)):
            d["group"] = group_of(target)
        d["entity_id"] = target.entity_id

    sections = {r.section for r in rows}
    if not keep_kind and d["kind"] not in sections and sections:
        d["kind"] = "ASSETS" if "ASSETS" in sections else "SHOTS"
    kind_rows = [r for r in rows if r.section == d["kind"]]
    if d["group"] not in {group_of(r) for r in kind_rows}:
        d["group"] = "ALL"
    shown = kind_rows if d["group"] == "ALL" else \
        [r for r in kind_rows if group_of(r) == d["group"]]

    entity_ids = _unique(r.entity_id for r in shown)
    if d["entity_id"] not in entity_ids:
        d["entity_id"] = entity_ids[0] if entity_ids else ""
    entity_rows = [r for r in shown if r.entity_id == d["entity_id"]]
    if task_id not in {r.task_id for r in entity_rows}:
        mine = [r for r in entity_rows if r.assigned_to_me]
        task_id = (mine or entity_rows)[0].task_id if entity_rows else ""
    d["selected_task"] = task_id

    busy = True
    try:
        state.browse_kind = d["kind"]
        try:
            state.group = d["group"]
        except TypeError:
            pass

        state.entities.clear()
        for i, eid in enumerate(entity_ids):
            ers = [r for r in shown if r.entity_id == eid]
            first = ers[0]
            item = state.entities.add()
            item.name = first.entity_name
            item.entity_id = eid
            item.kind = first.kind
            item.group = group_of(first)
            item.project_name = first.project_name
            item.description = first.description
            item.preview_file_id = first.preview_file_id
            item.task_count = len(ers)
            item.done_count = sum(r.status_done for r in ers)
            item.my_count = sum(r.assigned_to_me for r in ers)
            if eid == d["entity_id"]:
                state.entity_index = i
        if not entity_ids:
            state.entity_index = -1

        state.tasks.clear()
        state.task_index = -1
        for i, r in enumerate(entity_rows):
            item = state.tasks.add()
            item.name = r.task_type
            item.task_id = r.task_id
            item.project_id = r.project_id
            item.project_name = r.project_name
            item.kind = r.kind
            item.entity_id = r.entity_id
            item.entity_name = r.entity_name
            item.label = r.label
            item.task_type = r.task_type
            item.status = r.status
            item.status_kind = r.status_kind
            item.status_done = r.status_done
            item.assigned_to_me = r.assigned_to_me
            item.rel_path = r.rel_path
            if r.task_id == task_id:
                state.task_index = i
    finally:
        busy = False
    refresh_file_list(context)


# ------------------------------------------------------- property callbacks
def on_kind_changed(state, context):
    if busy or state.browse_kind == session.data["kind"]:
        return
    session.data.update(kind=state.browse_kind, group="ALL", entity_id="", selected_task="")
    rebuild(context, keep_kind=True)


def on_group_changed(state, context):
    if busy or state.group == session.data["group"]:
        return
    session.data.update(group=state.group, entity_id="", selected_task="")
    rebuild(context, keep_kind=True)


def on_entity_changed(state, context):
    if busy or not (0 <= state.entity_index < len(state.entities)):
        return
    entity = state.entities[state.entity_index]
    if entity.entity_id != session.data["entity_id"]:
        session.data.update(entity_id=entity.entity_id, selected_task="")
        rebuild(context, keep_kind=True)
    thumbs.kitsu_icon(entity.preview_file_id, download=True)


def on_task_changed(state, context):
    if busy or not (0 <= state.task_index < len(state.tasks)):
        return
    session.data["selected_task"] = state.tasks[state.task_index].task_id
    refresh_file_list(context)
