"""Write work progress to Kitsu. Kept free of bpy so it can be tested outside Blender.

Each saved version creates:
  * a working-file record (revision = version number, path = local file path)
  * a comment on the task (Kitsu changes task status through comments)
  * a preview revision on that comment with a viewport snapshot, when one is given.
    The preview revision is what Kitsu shows as the task's version.

Starting work (creating, opening or versioning up a file) moves the task to WIP,
but only from the statuses in START_FROM, so a task waiting for approval or
already approved is never pulled back by opening its file.
"""

import os

from .api import KitsuError

START_FROM = {"todo", "ready", "neutral", "retake"}


def _statuses(client):
    return {s["id"]: s for s in client.task_statuses()}


def _wip_status(statuses):
    for s in statuses.values():
        if s.get("is_wip"):
            return s
    for s in statuses.values():
        if s.get("short_name", "").lower() == "wip":
            return s
    return None


def _should_start(status):
    return bool(status) and (status.get("short_name", "").lower() in START_FROM
                             or bool(status.get("is_retake")))


def _target_status(client, task, set_wip):
    """Status the comment should carry: WIP if work is starting, otherwise unchanged."""
    statuses = _statuses(client)
    current = statuses.get(task["task_status_id"])
    if set_wip and _should_start(current):
        wip = _wip_status(statuses)
        if wip:
            return wip
    return current or {"id": task["task_status_id"], "short_name": "?", "is_done": False}


def start_work(client, task_id, text):
    """Move the task to WIP with a comment, if its status allows it.

    Returns the new status dict, or None when nothing changed.
    """
    task = client.task(task_id)
    status = _target_status(client, task, set_wip=True)
    if status["id"] == task["task_status_id"]:
        return None
    client.comment_task(task_id, status["id"], text)
    return status


def record_version(client, task_id, entity_id, filepath, version, note="", snapshot=None,
                   set_wip=True):
    """Returns (summary, new_status_or_None). Raises KitsuError on failure."""
    filename = os.path.basename(filepath)
    task = client.task(task_id)  # fresh copy, so the status we send back is current
    status = _target_status(client, task, set_wip)
    changed = status["id"] != task["task_status_id"]

    client.create_working_file(task_id, entity_id, version, filepath, note)

    text = f"**v{version:03d}** saved from Blender: `{filename}`"
    if note.strip():
        text += "\n\n" + note.strip()
    comment = client.comment_task(task_id, status["id"], text)

    summary = f"v{version:03d} recorded in Kitsu"
    if snapshot:
        try:
            preview = client.add_preview(task_id, comment["id"], version)
        except KitsuError:
            # That revision number already exists on the task: let Kitsu pick the next one.
            preview = client.add_preview(task_id, comment["id"])
        client.upload_preview(preview["id"], snapshot)
        summary += f" as revision {preview.get('revision')}"
    else:
        summary += " (no preview)"
    if changed:
        summary += f", status set to {status['short_name']}"
    return summary, (status if changed else None)
