import os

import bpy
from bpy.types import Panel, UIList

from . import session
from .api import client
from .props import active_task, get_prefs, get_state, latest_version, local_root

KIND_ICONS = {
    "SHOT": 'FILE_MOVIE',
    "ASSET": 'OUTLINER_OB_MESH',
    "SEQUENCE": 'SEQUENCE',
    "EPISODE": 'FILE_FOLDER',
    "OTHER": 'QUESTION',
}


class KITSU_UL_tasks(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        label = item.label
        if session.data["project_id"] == "ALL":
            label = f"{item.project_name}: {label}"
        row.label(text=label, icon=KIND_ICONS.get(item.kind, 'DOT'))
        sub = row.row(align=True)
        sub.alignment = 'RIGHT'
        sub.label(text=item.task_type)
        sub.label(text=item.status, icon='CHECKMARK' if item.status_done else 'NONE')


class KITSU_UL_files(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        current = bool(bpy.data.filepath) and \
            os.path.normcase(bpy.data.filepath) == os.path.normcase(item.filepath)
        row.label(text=item.name, icon='RADIOBUT_ON' if current else 'FILE_BLEND')
        op = row.operator("kitsu.open_file", text="", icon='FILEBROWSER')
        op.filepath = item.filepath


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
            box = layout.box()
            row = box.row()
            row.label(text=state.user_name, icon='USER')
            row.operator("kitsu.logout", text="", icon='X')
            box.label(text=state.server_label, icon='URL')
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
            layout.label(text=state.status_message, icon='INFO')


class KITSU_PT_local(KitsuPanelBase, Panel):
    bl_label = "Local Folder"
    bl_idname = "KITSU_PT_local"
    bl_parent_id = "KITSU_PT_main"

    def draw(self, context):
        layout = self.layout
        prefs = get_prefs(context)
        layout.prop(prefs, "root_dir", text="")
        if not prefs.root_dir:
            layout.label(text="Choose where project files live", icon='ERROR')
            return
        task = active_task(context)
        if task and session.data["project_id"] != "ALL":
            project_dir = os.path.join(local_root(context), task.rel_path.split(os.sep)[0])
            row = layout.row()
            row.label(text=project_dir, icon='FILE_FOLDER')
            row.label(text="", icon='CHECKMARK' if os.path.isdir(project_dir) else 'BLANK1')
        if client.logged_in:
            layout.operator("kitsu.build_folders", icon='NEWFOLDER')


class KITSU_PT_tasks(KitsuPanelBase, Panel):
    bl_label = "Tasks"
    bl_idname = "KITSU_PT_tasks"
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
        layout.prop(prefs, "only_my_tasks", toggle=True, icon='USER')

        layout.template_list("KITSU_UL_tasks", "", state, "tasks", state, "task_index", rows=8)
        if not state.tasks and prefs.only_my_tasks:
            layout.label(text="No tasks assigned to you here", icon='INFO')


class KITSU_PT_task_files(KitsuPanelBase, Panel):
    bl_label = "Task Files"
    bl_idname = "KITSU_PT_task_files"
    bl_parent_id = "KITSU_PT_main"

    @classmethod
    def poll(cls, context):
        return client.logged_in and active_task(context) is not None

    def draw(self, context):
        layout = self.layout
        prefs, state = get_prefs(context), get_state(context)
        task = active_task(context)

        col = layout.column(align=True)
        col.label(text=f"{task.project_name}  {task.label}", icon=KIND_ICONS.get(task.kind, 'DOT'))
        col.label(text=f"{task.task_type}  ·  {task.status}")
        col.label(text=task.rel_path, icon='FILE_FOLDER')

        if not prefs.root_dir:
            layout.label(text="Set the Local Folder first", icon='ERROR')
            return

        latest = latest_version(context)
        col = layout.column(align=True)
        col.scale_y = 1.3
        if latest == 0:
            col.operator("kitsu.new_task_file", text="Create First File (v001)", icon='FILE_NEW')
        else:
            col.operator("kitsu.version_up", text=f"Version Up (v{latest + 1:03d})",
                         icon='FILE_TICK')
        row = layout.row(align=True)
        row.prop(prefs, "record_in_kitsu", toggle=True, icon='EXPORT')
        row.prop(prefs, "attach_snapshot", text="", icon='IMAGE_DATA')
        row.prop(prefs, "set_wip", text="WIP", toggle=True, icon='PLAY')

        row = layout.row(align=True)
        row.operator("kitsu.open_task_folder", icon='FOLDER_REDIRECT')
        row.operator("kitsu.refresh_files", text="", icon='FILE_REFRESH')

        if state.files:
            layout.template_list("KITSU_UL_files", "", state, "files", state, "file_index", rows=4)
        else:
            layout.label(text="No .blend files for this task yet")


classes = (KITSU_UL_tasks, KITSU_UL_files, KITSU_PT_main, KITSU_PT_local,
           KITSU_PT_tasks, KITSU_PT_task_files)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
