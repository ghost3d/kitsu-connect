bl_info = {
    "name": "Kitsu Connect",
    "author": "Michael Kirylo",
    "version": (0, 3, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar > Kitsu",
    "description": "Browse your Kitsu tasks and manage task files",
    "category": "Pipeline",
}

from . import props, operators, thumbs, ui, uninstall  # noqa: E402

_modules = (props, thumbs, operators, uninstall, ui)


def register():
    for m in _modules:
        m.register()


def unregister():
    from .api import client
    client.logout()
    for m in reversed(_modules):
        m.unregister()
