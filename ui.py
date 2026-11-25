import os
import textwrap

import bpy
from bpy.types import Panel, UIList

from . import session, thumbs
from .api import client
from .props import active_task, get_prefs, get_state, latest_version, local_root

STATUS_ICONS = {
    "TODO": 'RADIOBUT_OFF',
    "WIP": 'TIME',
    "WFA": 'HIDE_OFF',
    "RETAKE": 'LOOP_BACK',
    "DONE": 'CHECKMARK',
}

# Icons for asset types, matched on words in the type name.
GROUP_ICONS = (
    ("character", 'OUTLINER_OB_ARMATURE'),
    ("prop", 'OBJECT_DATA'),
    ("environment", 'WORLD'),
    ("set", 'WORLD'),
    ("vehicle", 'AUTO'),
    ("fx", 'SHADERFX'),
    ("camera", 'CAMERA_DATA'),
)

FILES_SHOWN = 4  # file cards shown before "Show All Versions"


def entity_icon(item):
    if item.kind == "SHOT":
        return 'FILE_MOVIE'
    if item.kind in ("SEQUENCE", "EPISODE"):
        return 'SEQUENCE'
    group = item.group.lower()
    return next((icon for word, icon in GROUP_ICONS if word in group), 'OUTLINER_OB_MESH')


def wrapped_lines(layout, context, text, max_lines=6):
    """Draw text as labels, wrapped to the panel width."""
    width = max(16, int(context.region.width / (7 * context.preferences.view.ui_scale)) - 4)
    lines = textwrap.wrap(text, width) or [""]
    col = layout.column(align=True)
    col.scale_y = 0.8
    for line in lines[:max_lines]:
        col.label(text=line)
    if len(lines) > max_lines:
        col.label(text="…")


# ------------------------------------------------------------------ lists
class KITSU_UL_entities(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.name, icon=entity_icon(item))
        sub = row.row(align=True)
        sub.alignment = 'RIGHT'
        if item.done_count == item.task_count:
            sub.label(text="", icon='CHECKMARK')
        else:
            sub.active = False
            sub.label(text=f"{item.done_count}/{item.task_count}")


class KITSU_UL_tasks(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.task_type, icon=STATUS_ICONS.get(item.status_kind, 'DOT'))
        sub = row.row(align=True)
        sub.alignment = 'RIGHT'
        sub.label(text=item.status)
        if not get_prefs(context).only_my_tasks:
            sub.label(text="", icon='USER' if item.assigned_to_me else 'BLANK1')


# ----------------------------------------------------------------- panels
class KitsuPanelBase:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Kitsu'


class KITSU_PT_main(KitsuPanelBase, Panel):
    bl_label = "Kitsu Connect"
    bl_idname = "KITSU_PT_main"

    def draw(self, context):
        layout = self.layout
        prefs, state = get_prefs(context), get_state(context)

        if client.logged_in:
            row = layout.row(align=True)
            row.label(text=state.user_name, icon='USER')
            row.label(text=state.server_label.split("://")[-1], icon='URL')
            row.operator("kitsu.logout", text="", icon='X')
        else:
            col = layout.column()
            col.prop(prefs, "server_url", text="", icon='URL')
            col.prop(prefs, "email", text="", icon='USER')
            if prefs.remember_password:
                col.prop(prefs, "saved_password", text="", icon='LOCKED')
            else:
                col.prop(state, "password", text="", icon='LOCKED')
            col.prop(prefs, "remember_password")
            col.operator("kitsu.login", icon='LINKED')

        if state.status_message:
            row = layout.row()
            row.active = False
            row.label(text=state.status_message, icon='INFO')


class KITSU_PT_browser(KitsuPanelBase, Panel):
    bl_label = "Browser"
    bl_idname = "KITSU_PT_browser"
    bl_parent_id = "KITSU_PT_main"

    @classmethod
    def poll(cls, context):
        return client.logged_in

    def draw(self, context):
        layout = self.layout
        prefs, state = get_prefs(context), get_state(context)

        row = layout.row(align=True)
        row.prop(state, "project", text="", icon='FILE_FOLDER')
        row.operator("kitsu.refresh_tasks", text="", icon='FILE_REFRESH')

        row = layout.row(align=True)
        row.scale_y = 1.2
        row.prop(state, "browse_kind", expand=True)

        row = layout.row(align=True)
        row.prop(state, "group", text="")
        row.prop(prefs, "only_my_tasks", text="", icon='USER', toggle=True)

        layout.template_list("KITSU_UL_entities", "", state, "entities", state, "entity_index",
                             rows=6)
        if not state.entities:
            what = "assets" if state.browse_kind == 'ASSETS' else "shots"
            mine = " assigned to you" if prefs.only_my_tasks else ""
            layout.label(text=f"No {what}{mine} here", icon='INFO')
            return

        entity = state.entities[state.entity_index] if \
            0 <= state.entity_index < len(state.entities) else None
        if entity is None:
            return
        icon = thumbs.kitsu_icon(entity.preview_file_id)
        if not (entity.description or icon):
            return
        box = layout.box()
        if icon:
            row = box.row()
            row.alignment = 'CENTER'
            row.template_icon(icon_value=icon, scale=6.0)
        if entity.description:
            wrapped_lines(box, context, entity.description)


class KITSU_PT_tasks(KitsuPanelBase, Panel):
    bl_label = "Tasks"
    bl_idname = "KITSU_PT_tasks"
    bl_parent_id = "KITSU_PT_main"

    @classmethod
    def poll(cls, context):
        return client.logged_in and len(get_state(context).tasks) > 0

    def draw_header(self, context):
        task = active_task(context)
        if task:
            self.layout.label(text=task.entity_name)

    def draw(self, context):
        state = get_state(context)
        self.layout.template_list("KITSU_UL_tasks", "", state, "tasks", state, "task_index",
                                  rows=min(max(len(state.tasks), 2), 6))


class KITSU_PT_task_files(KitsuPanelBase, Panel):
    bl_label = "Files"
    bl_idname = "KITSU_PT_task_files"
    bl_parent_id = "KITSU_PT_main"

    @classmethod
    def poll(cls, context):
        return client.logged_in and active_task(context) is not None

    def draw_header(self, context):
        self.layout.label(text=active_task(context).task_type)

    def draw(self, context):
        layout = self.layout
        prefs, state = get_prefs(context), get_state(context)

        if not prefs.root_dir:
            layout.label(text="Set the Local Folder first", icon='ERROR')
            return

        latest = latest_version(context)
        row = layout.row(align=True)
        row.scale_y = 1.4
        if latest == 0:
            row.operator("kitsu.new_task_file", text="Create First File (v001)", icon='FILE_NEW')
        else:
            row.operator("kitsu.version_up", text=f"Version Up (v{latest + 1:03d})",
                         icon='FILE_TICK')

        row = layout.row(align=True)
        row.prop(prefs, "record_in_kitsu", text="Record", toggle=True, icon='EXPORT')
        row.prop(prefs, "attach_snapshot", text="", icon='IMAGE_DATA')
        row.prop(prefs, "set_wip", text="WIP", toggle=True, icon='PLAY')

        row = layout.row(align=True)
        row.label(text=f"Versions ({len(state.files)})")
        row.operator("kitsu.open_task_folder", text="", icon='FOLDER_REDIRECT', emboss=False)
        row.operator("kitsu.refresh_files", text="", icon='FILE_REFRESH', emboss=False)

        if not state.files:
            row = layout.row()
            row.active = False
            row.label(text="No .blend files for this task yet", icon='FILE_BLEND')
            return

        current = os.path.normcase(bpy.data.filepath) if bpy.data.filepath else ""
        shown = state.files if state.show_all_files else list(state.files)[:FILES_SHOWN]
        col = layout.column(align=True)
        for f in shown:
            self._draw_card(col, f, current == os.path.normcase(f.filepath))
        hidden = len(state.files) - FILES_SHOWN
        if hidden > 0:
            text = "Show Fewer" if state.show_all_files else f"Show All Versions (+{hidden})"
            layout.prop(state, "show_all_files", text=text, toggle=True,
                        icon='TRIA_UP' if state.show_all_files else 'TRIA_DOWN')

    @staticmethod
    def _draw_card(layout, f, is_open):
        box = layout.box()
        split = box.split(factor=0.36)
        icon = thumbs.blend_icon(f.filepath)
        left = split.column()
        if icon:
            left.template_icon(icon_value=icon, scale=3.4)
        else:
            left.label(text="", icon='FILE_BLEND')

        right = split.column(align=True)
        title = f"v{f.version:03d}" if f.version else f.name
        head = right.row(align=True)
        head.label(text=title, icon='RADIOBUT_ON' if is_open else 'FILE_BLEND')
        op = head.operator("kitsu.open_file", text="", icon='FILEBROWSER', emboss=not is_open)
        op.filepath = f.filepath
        sub = right.column(align=True)
        sub.active = False
        sub.label(text=f.modified, icon='TIME')
        sub.label(text=f.size, icon='DISK_DRIVE')


class KITSU_PT_local(KitsuPanelBase, Panel):
    bl_label = "Local Folder"
    bl_idname = "KITSU_PT_local"
    bl_parent_id = "KITSU_PT_main"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        prefs = get_prefs(context)
        layout.prop(prefs, "root_dir", text="")
        if not prefs.root_dir:
            layout.label(text="Choose where project files live", icon='ERROR')
            return
        task = active_task(context)
        if task and session.data["project_id"] != "ALL":
            # <local>/<project>/Source: everything the add-on creates lives in here
            project_dir = os.path.join(local_root(context), *task.rel_path.split(os.sep)[:2])
            row = layout.row()
            row.label(text=project_dir, icon='FILE_FOLDER')
            row.label(text="", icon='CHECKMARK' if os.path.isdir(project_dir) else 'BLANK1')
        if client.logged_in:
            layout.operator("kitsu.build_folders", icon='NEWFOLDER')


class KITSU_PT_settings(KitsuPanelBase, Panel):
    bl_label = "Settings"
    bl_idname = "KITSU_PT_settings"
    bl_parent_id = "KITSU_PT_main"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        prefs = get_prefs(context)
        col = layout.column()
        col.prop(prefs, "record_in_kitsu")
        col.prop(prefs, "attach_snapshot")
        col.prop(prefs, "set_wip")
        layout.separator()
        layout.operator("kitsu.uninstall", icon='TRASH')


classes = (KITSU_UL_entities, KITSU_UL_tasks, KITSU_PT_main, KITSU_PT_browser,
           KITSU_PT_tasks, KITSU_PT_task_files, KITSU_PT_local, KITSU_PT_settings)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
