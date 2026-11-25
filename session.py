"""In-memory session data.

Kept in Python rather than on the WindowManager, because opening a .blend can
replace the WindowManager and the UI state stored on it. A load_post handler
copies this back into the UI after every file load.
"""

data = {
    "rows": [],           # tasks.TaskRow for every open project
    "projects": [],       # [(project_id, name)]
    "project_id": "",     # selected project, or "ALL"
    "kind": "ASSETS",     # browser side: ASSETS or SHOTS
    "group": "ALL",       # asset type or sequence shown, or "ALL"
    "entity_id": "",      # selected asset or shot
    "selected_task": "",  # selected task id
    "message": "",
}


def clear():
    data.update(rows=[], projects=[], project_id="", kind="ASSETS", group="ALL", entity_id="",
                selected_task="", message="")
