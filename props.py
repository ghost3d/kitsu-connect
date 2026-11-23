import os

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, IntProperty,
                       PointerProperty, StringProperty)
from bpy.types import AddonPreferences, PropertyGroup

from . import session, tasks

ADDON_ID = __package__


def get_prefs(context=None):
    context = context or bpy.context
    return context.preferences.addons[ADDON_ID].preferences


def get_state(context=None):
    return (context or bpy.context).window_manager.kitsu


# ---------------------------------------------------------------- callbacks
def _on_remember_changed(self, context):
    state = get_state(context)
    if self.remember_password:
        self.saved_password = state.password
    else:
        state.password = self.saved_password
        self.saved_password = ""


def _on_only_mine_changed(self, context):
    from .api import KitsuError, client
    from .operators import load_tasks
    if client.logged_in:
        try:
            load_tasks(context)
        except KitsuError as e:
            get_state(context).status_message = str(e)


def _on_task_selected(self, context):
    task = active_task(context)
    if task:
        session.data["selected_task"] = task.task_id
    refresh_file_list(context)


# Blender needs the enum item list kept alive in Python, or labels turn to garbage.
_project_items = []


def _get_project_items(self, context):
    global _project_items
    projects = session.data["projects"]
    items = [(pid, name, f"Show tasks of {name}") for pid, name in projects]
    if len(projects) > 1:
        items.append(("ALL", "All Projects", "Show tasks of every open project"))
    _project_items = items or [("NONE", "No Projects", "")]
    return _project_items


def _on_project_changed(self, context):
    if self.project == "NONE" or self.project == session.data["project_id"]:
        return
    from .operators import fill_state
    session.data["project_id"] = self.project
    fill_state(context)


# ------------------------------------------------------------------ classes
class KitsuPreferences(AddonPreferences):
    bl_idname = ADDON_ID

    server_url: StringProperty(
        name="Server", default="http://127.0.0.1:8012",
        description="Kitsu server address, e.g. http://127.0.0.1:8012")
    email: StringProperty(name="Email", description="The email you log in to Kitsu with")
    remember_password: BoolProperty(
        name="Remember Password", default=False, update=_on_remember_changed,
        description="Store the password in Blender's preferences file (plain text)")
    saved_password: StringProperty(name="Password", subtype='PASSWORD')
    root_dir: StringProperty(
        name="Local Folder", subtype='DIR_PATH',
        description="Folder on this computer that holds your project folders. Kitsu files go "
                    "in <project>/Source, e.g. D:/projects  ->  D:/projects/DEV/Source/shots/...")
    only_my_tasks: BoolProperty(
        name="Only My Tasks", default=True, update=_on_only_mine_changed,
        description="Only list tasks assigned to you. Off lists every task in the project")
    record_in_kitsu: BoolProperty(
        name="Record in Kitsu", default=True,
        description="When saving a new version, add it to the task in Kitsu")
    set_wip: BoolProperty(
        name="Set Task to WIP", default=True,
        description="When you create, open or version up a task file, move the task to WIP "
                    "in Kitsu if it is todo, ready, neutral or retake")
    attach_snapshot: BoolProperty(
        name="Attach Viewport Snapshot", default=True,
        description="Upload a screenshot of the 3D viewport as the version's preview")

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "server_url")
        col.prop(self, "email")
        col.prop(self, "remember_password")
        if self.remember_password:
            col.prop(self, "saved_password")
        col.prop(self, "root_dir")
        col.prop(self, "record_in_kitsu")
        col.prop(self, "attach_snapshot")
        col.prop(self, "set_wip")
        self.layout.separator()
        self.layout.operator("kitsu.uninstall", icon='TRASH')


class KitsuTaskItem(PropertyGroup):
    # `name` (built in) holds the search text the list filter matches on.
    task_id: StringProperty()
    project_id: StringProperty()
    project_name: StringProperty()
    kind: StringProperty()
    entity_id: StringProperty()
    entity_name: StringProperty()
    label: StringProperty()
    task_type: StringProperty()
    status: StringProperty()
    status_done: BoolProperty()
    assigned_to_me: BoolProperty()
    rel_path: StringProperty()


class KitsuFileItem(PropertyGroup):
    filepath: StringProperty()
    version: IntProperty(default=-1)


class KitsuState(PropertyGroup):
    """Session UI state. Lives on the WindowManager, so it is never saved into .blend files."""
    password: StringProperty(name="Password", subtype='PASSWORD', options={'SKIP_SAVE'})
    logged_in: BoolProperty(default=False)
    user_name: StringProperty()
    server_label: StringProperty()
    status_message: StringProperty()
    project: EnumProperty(name="Project", items=_get_project_items, update=_on_project_changed,
                          description="Kitsu project to browse")
    tasks: CollectionProperty(type=KitsuTaskItem)
    task_index: IntProperty(default=-1, update=_on_task_selected)
    files: CollectionProperty(type=KitsuFileItem)
    file_index: IntProperty(default=-1)


# ------------------------------------------------------------------ helpers
def active_task(context=None):
    state = get_state(context)
    if 0 <= state.task_index < len(state.tasks):
        return state.tasks[state.task_index]
    return None


def local_root(context=None):
    root = get_prefs(context).root_dir
    return bpy.path.abspath(root) if root else ""


def task_folder(task, context=None):
    root = local_root(context)
    if not root or task is None:
        return ""
    return os.path.normpath(os.path.join(root, task.rel_path))


def latest_version(context=None):
    """Highest version number in the selected task's file list, 0 if none."""
    return max((f.version for f in get_state(context).files), default=0)


def refresh_file_list(context=None):
    state = get_state(context)
    state.files.clear()
    folder = task_folder(active_task(context), context)
    for name, version, _mtime in tasks.list_blend_files(folder):
        item = state.files.add()
        item.name = name
        item.filepath = os.path.join(folder, name)
        item.version = version if version is not None else 0
    state.file_index = 0 if state.files else -1


classes = (KitsuPreferences, KitsuTaskItem, KitsuFileItem, KitsuState)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.WindowManager.kitsu = PointerProperty(type=KitsuState)


def unregister():
    del bpy.types.WindowManager.kitsu
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
