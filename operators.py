import os
import tempfile
import uuid

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator

from . import browser, publish, session, tasks
from .api import KitsuError, client, is_local_host, normalize_host
from .props import (active_task, get_prefs, get_state, local_root,
                    refresh_file_list, task_folder)


def _password(context):
    prefs = get_prefs(context)
    return prefs.saved_password if prefs.remember_password else get_state(context).password


def _online_access_blocked(url):
    # Blender 4.2+ lets users turn off internet access; a local server is still allowed.
    return not getattr(bpy.app, "online_access", True) and not is_local_host(url)


# ------------------------------------------------------------ task loading
def load_tasks(context):
    """Fetch projects and tasks from Kitsu into the session, then refresh the UI."""
    prefs = get_prefs(context)
    projects = client.open_projects()
    session.data["projects"] = [(p["id"], p["name"]) for p in projects]
    session.data["rows"] = tasks.collect_tasks(client, only_mine=prefs.only_my_tasks,
                                               projects=projects)
    valid = {pid for pid, _ in session.data["projects"]} | {"ALL"}
    if session.data["project_id"] not in valid:
        session.data["project_id"] = projects[0]["id"] if projects else ""
    fill_state(context)
    return len(browser.project_rows())


def fill_state(context, selected_id=None):
    """Copy session data into the WindowManager UI state."""
    prefs, state = get_prefs(context), get_state(context)
    pid = session.data["project_id"]

    state.logged_in = client.logged_in
    state.user_name = (client.user or {}).get("full_name") or prefs.email
    state.server_label = client.host
    if pid:
        try:
            state.project = pid
        except TypeError:
            pass
    browser.rebuild(context, selected_id)

    rows = browser.project_rows()
    scope = "assigned to you" if prefs.only_my_tasks else "in project"
    session.data["message"] = f"{len(rows)} tasks {scope}"
    state.status_message = session.data["message"]


def _task_for_file(filepath):
    """Find the task row whose folder holds the given .blend file."""
    root = local_root()
    if not filepath or not root:
        return None
    folder = os.path.normcase(os.path.dirname(os.path.abspath(filepath)))
    for r in session.data["rows"]:
        if os.path.normcase(os.path.abspath(os.path.join(root, r.rel_path))) == folder:
            return r
    return None


def _apply_status(task_id, status):
    """Update the cached task row after Kitsu changed its status."""
    if not status:
        return
    for r in session.data["rows"]:
        if r.task_id == task_id:
            r.task_status_id = status["id"]
            r.status = status.get("short_name", r.status)
            r.status_done = bool(status.get("is_done"))
            r.status_kind = tasks.status_kind(status)


def _start_work_on_open(row, filepath):
    """Opening a task file means work has started: move the task to WIP if allowed."""
    if not get_prefs().set_wip:
        return
    try:
        status = publish.start_work(
            client, row.task_id, f"Opened `{os.path.basename(filepath)}` in Blender")
    except KitsuError as e:
        print(f"Kitsu Connect: could not set {row.label} {row.task_type} to WIP: {e}")
        return
    _apply_status(row.task_id, status)
    if status:
        return f"{row.entity_name} {row.task_type} set to {status['short_name']}"


@bpy.app.handlers.persistent
def _restore_after_load(_dummy=None):
    if not client.logged_in:
        return
    row = _task_for_file(bpy.data.filepath)
    note = None
    if row:
        session.data["selected_task"] = row.task_id
        if session.data["project_id"] not in ("ALL", row.project_id):
            session.data["project_id"] = row.project_id
        note = _start_work_on_open(row, bpy.data.filepath)
    fill_state(bpy.context)
    if note:
        get_state().status_message = note


# ------------------------------------------------------------ connection
class KITSU_OT_login(Operator):
    """Log in to the Kitsu server"""
    bl_idname = "kitsu.login"
    bl_label = "Log In"

    def execute(self, context):
        prefs, state = get_prefs(context), get_state(context)
        if not prefs.email or not _password(context):
            self.report({'ERROR'}, "Enter your email and password")
            return {'CANCELLED'}
        if _online_access_blocked(prefs.server_url):
            self.report({'ERROR'}, "Online access is off in Preferences > System > Network")
            return {'CANCELLED'}
        try:
            client.login(prefs.server_url, prefs.email, _password(context))
        except KitsuError as e:
            state.logged_in = False
            state.status_message = str(e)
            self.report({'ERROR'}, f"Login failed: {e}")
            return {'CANCELLED'}

        prefs.server_url = normalize_host(prefs.server_url)
        if not prefs.remember_password:
            state.password = ""  # the client keeps it in memory for re-login
        state.logged_in = True
        try:
            n = load_tasks(context)
        except KitsuError as e:
            self.report({'WARNING'}, f"Logged in, but loading tasks failed: {e}")
            return {'FINISHED'}
        self.report({'INFO'}, f"Logged in as {state.user_name}: {n} tasks")
        return {'FINISHED'}


class KITSU_OT_logout(Operator):
    """Log out of the Kitsu server"""
    bl_idname = "kitsu.logout"
    bl_label = "Log Out"

    def execute(self, context):
        client.logout()
        session.clear()
        state = get_state(context)
        state.logged_in = False
        state.user_name = ""
        state.entities.clear()
        state.tasks.clear()
        state.files.clear()
        state.entity_index = -1
        state.task_index = -1
        state.status_message = "Logged out"
        return {'FINISHED'}


class KITSU_OT_refresh_tasks(Operator):
    """Reload projects and tasks from Kitsu"""
    bl_idname = "kitsu.refresh_tasks"
    bl_label = "Refresh Tasks"

    @classmethod
    def poll(cls, context):
        return client.logged_in

    def execute(self, context):
        try:
            n = load_tasks(context)
        except KitsuError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, f"{n} tasks loaded")
        return {'FINISHED'}


# --------------------------------------------------------------- folders
def _require_root(op, context):
    if not get_prefs(context).root_dir:
        op.report({'ERROR'}, "Set the Local Folder first")
        return False
    return True


class KITSU_OT_build_folders(Operator):
    """Create the local folder of every task listed, mirroring the shots and assets in Kitsu"""
    bl_idname = "kitsu.build_folders"
    bl_label = "Create Task Folders"

    @classmethod
    def poll(cls, context):
        return bool(browser.project_rows())

    def execute(self, context):
        if not _require_root(self, context):
            return {'CANCELLED'}
        paths = [r.rel_path for r in browser.project_rows()]
        try:
            created = tasks.build_folders(local_root(context), paths)
        except OSError as e:
            self.report({'ERROR'}, f"Could not create folders: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Created {created} folders "
                              f"({len(paths) - created} already existed)")
        return {'FINISHED'}


class KITSU_OT_open_task_folder(Operator):
    """Create (if needed) and open the selected task's folder in the system file browser"""
    bl_idname = "kitsu.open_task_folder"
    bl_label = "Open Folder"

    @classmethod
    def poll(cls, context):
        return active_task(context) is not None

    def execute(self, context):
        if not _require_root(self, context):
            return {'CANCELLED'}
        folder = task_folder(active_task(context), context)
        os.makedirs(folder, exist_ok=True)
        bpy.ops.wm.path_open(filepath=folder)
        return {'FINISHED'}


class KITSU_OT_refresh_files(Operator):
    """Rescan the selected task's folder for .blend files"""
    bl_idname = "kitsu.refresh_files"
    bl_label = "Rescan Files"

    def execute(self, context):
        refresh_file_list(context)
        return {'FINISHED'}


class KITSU_OT_open_file(Operator):
    """Open this .blend file"""
    bl_idname = "kitsu.open_file"
    bl_label = "Open File"

    filepath: StringProperty(subtype='FILE_PATH', options={'SKIP_SAVE'})

    def invoke(self, context, event):
        if bpy.data.is_dirty:
            return context.window_manager.invoke_confirm(
                self, event, title="Open File",
                message="The current file has unsaved changes that will be lost.",
                confirm_text="Open Anyway")
        return self.execute(context)

    def execute(self, context):
        if not os.path.isfile(self.filepath):
            self.report({'ERROR'}, f"File not found: {self.filepath}")
            return {'CANCELLED'}
        bpy.ops.wm.open_mainfile(filepath=self.filepath)
        return {'FINISHED'}


# ------------------------------------------------------- saving versions
def _viewport_snapshot():
    """Screenshot the largest 3D viewport to a temp PNG. Returns its path or None."""
    context = bpy.context
    window = context.window or (context.window_manager.windows[0]
                                if context.window_manager.windows else None)
    if bpy.app.background or window is None:
        return None
    areas = [a for a in window.screen.areas if a.type == 'VIEW_3D']
    if not areas:
        return None
    area = max(areas, key=lambda a: a.width * a.height)
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    path = os.path.join(bpy.app.tempdir or tempfile.gettempdir(),
                        f"kitsu_snapshot_{uuid.uuid4().hex[:8]}.png")
    try:
        with context.temp_override(window=window, screen=window.screen, area=area, region=region):
            bpy.ops.screen.screenshot_area(filepath=path, check_existing=False)
    except Exception as e:  # never block a save because of the preview
        print(f"Kitsu Connect: viewport snapshot failed: {e}")
        return None
    return path if os.path.isfile(path) else None


THUMB_WIDTH = 320


def _write_thumbnail(snapshot, blend_path):
    """Save a small copy of the snapshot as the version's thumbnail in the browser."""
    dest = tasks.thumbnail_path(blend_path)
    img = None
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        img = bpy.data.images.load(snapshot, check_existing=False)
        w, h = img.size
        if w > THUMB_WIDTH:
            img.scale(THUMB_WIDTH, max(1, round(h * THUMB_WIDTH / w)))
        img.filepath_raw = dest
        img.file_format = 'PNG'
        img.save()
    except Exception as e:  # a missing thumbnail must never block a save
        print(f"Kitsu Connect: could not write thumbnail: {e}")
    finally:
        if img is not None:
            bpy.data.images.remove(img)


def _task_info(task):
    """Plain copy of a task item; the item itself can be freed when a file loads."""
    return {k: getattr(task, k) for k in
            ("task_id", "entity_id", "project_name", "entity_name", "task_type", "rel_path")}


def _target_path(context, info, version):
    folder = os.path.normpath(os.path.join(local_root(context), info["rel_path"]))
    name = tasks.version_filename(info["project_name"], info["entity_name"],
                                  info["task_type"], version)
    return os.path.join(folder, name)


def _save_version(op, context, info, version, note, record):
    path = _target_path(context, info, version)
    if os.path.exists(path):
        op.report({'ERROR'}, f"{os.path.basename(path)} already exists")
        return {'CANCELLED'}
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError as e:
        op.report({'ERROR'}, f"Could not create the task folder: {e}")
        return {'CANCELLED'}

    # Snapshot before saving: the thumbnail work adds an image to the file, and doing it
    # first means the saved file is left clean.
    snapshot = _viewport_snapshot()
    try:
        if snapshot:
            _write_thumbnail(snapshot, path)
        bpy.ops.wm.save_as_mainfile(filepath=path)
        return _after_save(op, context, info, path, version, note, record,
                           snapshot if get_prefs(context).attach_snapshot else None)
    finally:
        if snapshot and os.path.isfile(snapshot):
            os.remove(snapshot)


def _after_save(op, context, info, path, version, note, record, snapshot):
    session.data["selected_task"] = info["task_id"]
    refresh_file_list(bpy.context)
    msg = f"Saved {os.path.basename(path)}"

    set_wip = get_prefs(context).set_wip
    status = None
    if client.logged_in and record:
        try:
            summary, status = publish.record_version(
                client, info["task_id"], info["entity_id"], path, version, note, snapshot,
                set_wip=set_wip)
            msg += ". " + summary
        except (KitsuError, OSError) as e:
            op.report({'WARNING'}, f"{msg}, but recording it in Kitsu failed: {e}")
            return {'FINISHED'}
    elif client.logged_in and set_wip:
        # Not recording the version, but work has still started on the task.
        try:
            status = publish.start_work(client, info["task_id"],
                                        f"Started `{os.path.basename(path)}` in Blender")
        except KitsuError as e:
            op.report({'WARNING'}, f"{msg}, but setting the task to WIP failed: {e}")
            return {'FINISHED'}
        if status:
            msg += f". Status set to {status['short_name']}"

    if status:
        _apply_status(info["task_id"], status)
        fill_state(bpy.context, info["task_id"])
    op.report({'INFO'}, msg)
    return {'FINISHED'}


def _file_in_task(context, task):
    folder = task_folder(task, context)
    return bool(bpy.data.filepath) and os.path.normcase(
        os.path.dirname(os.path.abspath(bpy.data.filepath))) == os.path.normcase(folder)


class _SaveVersionBase:
    note: StringProperty(name="Comment", description="Optional note added to the Kitsu comment",
                         options={'SKIP_SAVE'})
    record: BoolProperty(name="Record in Kitsu", default=True, options={'SKIP_SAVE'},
                         description="Add this version to the task in Kitsu")

    @classmethod
    def poll(cls, context):
        return active_task(context) is not None and bool(get_prefs(context).root_dir)

    def _draw_common(self, layout):
        layout.prop(self, "record")
        row = layout.row()
        row.enabled = self.record
        row.prop(self, "note")


class KITSU_OT_new_file(_SaveVersionBase, Operator):
    """Create the first file (v001) for the selected task"""
    bl_idname = "kitsu.new_task_file"
    bl_label = "Create First File"

    source: EnumProperty(
        name="Start From",
        items=[('CURRENT', "Current Scene", "Save the scene that is open now as v001"),
               ('STARTUP', "New Scene", "Start from Blender's startup file")],
        default='CURRENT', options={'SKIP_SAVE'})

    def invoke(self, context, event):
        self.record = get_prefs(context).record_in_kitsu
        return context.window_manager.invoke_props_dialog(
            self, width=420, title="Create First File", confirm_text="Create")

    def draw(self, context):
        layout = self.layout
        info = _task_info(active_task(context))
        layout.label(text=os.path.basename(_target_path(context, info, 1)), icon='FILE_BLEND')
        layout.prop(self, "source", expand=True)
        if self.source == 'STARTUP' and bpy.data.is_dirty:
            layout.label(text="Unsaved changes in the open file will be lost", icon='ERROR')
        self._draw_common(layout)

    def execute(self, context):
        info = _task_info(active_task(context))
        note, record = self.note, self.record
        folder = os.path.dirname(_target_path(context, info, 1))
        if tasks.next_version(folder) != 1:
            self.report({'ERROR'}, "This task already has files. Use Version Up instead")
            return {'CANCELLED'}
        if self.source == 'STARTUP':
            bpy.ops.wm.read_homefile()
        return _save_version(self, bpy.context, info, 1, note, record)


class KITSU_OT_version_up(_SaveVersionBase, Operator):
    """Save the current scene as the next version of the selected task"""
    bl_idname = "kitsu.version_up"
    bl_label = "Version Up"

    def invoke(self, context, event):
        self.record = get_prefs(context).record_in_kitsu
        return context.window_manager.invoke_props_dialog(
            self, width=420, title="Version Up", confirm_text="Save")

    def draw(self, context):
        layout = self.layout
        task = active_task(context)
        version = tasks.next_version(task_folder(task, context))
        layout.label(text=os.path.basename(_target_path(context, _task_info(task), version)),
                     icon='FILE_BLEND')
        if not _file_in_task(context, task):
            box = layout.box()
            box.label(text="The open file is not from this task.", icon='ERROR')
            box.label(text=f"It will be saved into {task.label} / {task.task_type}.")
        self._draw_common(layout)

    def execute(self, context):
        task = active_task(context)
        info = _task_info(task)
        version = tasks.next_version(task_folder(task, context))
        return _save_version(self, context, info, version, self.note, self.record)


classes = (
    KITSU_OT_login,
    KITSU_OT_logout,
    KITSU_OT_refresh_tasks,
    KITSU_OT_build_folders,
    KITSU_OT_open_task_folder,
    KITSU_OT_refresh_files,
    KITSU_OT_open_file,
    KITSU_OT_new_file,
    KITSU_OT_version_up,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.app.handlers.load_post.append(_restore_after_load)


def unregister():
    if _restore_after_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_restore_after_load)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
