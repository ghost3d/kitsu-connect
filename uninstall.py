"""Uninstall Kitsu Connect from inside Blender.

How it is removed depends on how it was installed:
  EXTENSION  installed from a zip as an extension  -> Blender's extension uninstall
  ADDON      a legacy add-on in Blender's own scripts/addons folder -> files removed
  DEV        loaded from a script directory or a git checkout -> only disabled, files kept,
             so a development folder is never deleted

Local project files (the Source/ folders and .blend files) and Kitsu data are never touched.
"""

import os
import shutil

import addon_utils
import bpy
from bpy.props import BoolProperty
from bpy.types import Operator

from .api import client

PACKAGE = __package__
ADDON_FOLDER = os.path.dirname(os.path.abspath(__file__))


def _same_dir(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def install_info():
    folder = ADDON_FOLDER
    has_git = os.path.isdir(os.path.join(folder, ".git"))

    if PACKAGE.startswith("bl_ext."):
        _, repo_module, pkg_id = PACKAGE.split(".", 2)
        repos = bpy.context.preferences.extensions.repos
        index = next((i for i, r in enumerate(repos) if r.module == repo_module), -1)
        if index >= 0:
            repo = repos[index]
            # A repo with a custom directory may point at a development checkout: keep it.
            if not (repo.use_custom_directory and has_git) \
                    and _same_dir(os.path.dirname(folder), repo.directory):
                return {"kind": "EXTENSION", "folder": folder,
                        "repo_index": index, "pkg_id": pkg_id}
        return {"kind": "DEV", "folder": folder}

    user_addons = bpy.utils.user_resource('SCRIPTS', path="addons")
    if not has_git and _same_dir(os.path.dirname(folder), user_addons):
        return {"kind": "ADDON", "folder": folder}
    return {"kind": "DEV", "folder": folder}


def _window_override():
    # Blender's preference operators redraw the calling area, which a timer doesn't have.
    wm = bpy.context.window_manager
    window = wm.windows[0] if wm.windows else None
    if window is None:
        return {}
    area = window.screen.areas[0] if window.screen.areas else None
    return {"window": window, "screen": window.screen, "area": area}


def uninstall_now(info):
    """Do the removal. Runs from a timer, after the operator that asked for it has finished."""
    try:
        if info["kind"] == "EXTENSION":
            with bpy.context.temp_override(**_window_override()):
                bpy.ops.extensions.package_uninstall(repo_index=info["repo_index"],
                                                     pkg_id=info["pkg_id"])
        else:
            addon_utils.disable(PACKAGE, default_set=True)
            if info["kind"] == "ADDON":
                shutil.rmtree(info["folder"])
        bpy.context.preferences.is_dirty = True  # so the change is saved with the preferences
    except Exception as e:
        print(f"Kitsu Connect: uninstall failed: {e}")
    return None  # one-shot timer


class KITSU_OT_uninstall(Operator):
    """Log out and remove the Kitsu Connect add-on from Blender"""
    bl_idname = "kitsu.uninstall"
    bl_label = "Uninstall Kitsu Connect"

    clear_login: BoolProperty(
        name="Forget Saved Login", default=True,
        description="Clear the saved server, email and password from the preferences first")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(
            self, width=460, title="Uninstall Kitsu Connect", confirm_text="Uninstall")

    def draw(self, context):
        info = install_info()
        col = self.layout.column(align=True)
        if info["kind"] == "DEV":
            col.label(text="Loaded from a development folder:", icon='INFO')
            col.label(text=info["folder"])
            col.label(text="It will be turned off. Its files are kept.")
        else:
            col.label(text="This removes the add-on files from:", icon='TRASH')
            col.label(text=info["folder"])
        col.separator()
        col.label(text="Your project files and your data in Kitsu are not touched.",
                  icon='CHECKMARK')
        self.layout.prop(self, "clear_login")

    def execute(self, context):
        info = install_info()
        client.logout()
        if self.clear_login:
            prefs = context.preferences.addons[PACKAGE].preferences
            prefs.saved_password = ""
            prefs.remember_password = False
            prefs.email = ""
        # Removing an add-on from inside its own operator would unregister the operator
        # while it runs, so the removal happens a moment later.
        bpy.app.timers.register(lambda: uninstall_now(info), first_interval=0.1)
        action = "turned off" if info["kind"] == "DEV" else "uninstalled"
        self.report({'INFO'}, f"Kitsu Connect will be {action}")
        return {'FINISHED'}


def register():
    bpy.utils.register_class(KITSU_OT_uninstall)


def unregister():
    bpy.utils.unregister_class(KITSU_OT_uninstall)
