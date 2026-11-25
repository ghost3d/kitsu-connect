"""Thumbnails for the browser: .blend file previews and Kitsu entity thumbnails."""

import os
import tempfile

import bpy.utils.previews

from .api import KitsuError, client
from .tasks import thumbnail_path

_pcoll = None
_failed = set()   # Kitsu preview ids that could not be downloaded this session


def _cache_dir():
    path = os.path.join(tempfile.gettempdir(), "kitsu_connect_thumbs")
    os.makedirs(path, exist_ok=True)
    return path


def blend_icon(filepath):
    """Icon id of a version's thumbnail (written next to it when saved), 0 if it has none."""
    thumb = thumbnail_path(filepath)
    if _pcoll is None or not os.path.isfile(thumb):
        return 0
    key = f"{thumb}|{os.path.getmtime(thumb)}"
    if key not in _pcoll:
        _pcoll.load(key, thumb, 'IMAGE')
    return _pcoll[key].icon_id


def kitsu_icon(preview_file_id, download=False):
    """Icon id of an entity's Kitsu thumbnail (0 if none).

    Panels draw with download=False so drawing never waits on the network; the thumbnail is
    fetched when the entity is selected.
    """
    if _pcoll is None or not preview_file_id or preview_file_id in _failed:
        return 0
    key = "kitsu|" + preview_file_id
    if key not in _pcoll:
        path = os.path.join(_cache_dir(), preview_file_id + ".png")
        if not os.path.isfile(path):
            if not download:
                return 0
            try:
                client.thumbnail(preview_file_id, path)
            except (KitsuError, OSError) as e:
                print(f"Kitsu Connect: no thumbnail for {preview_file_id}: {e}")
                _failed.add(preview_file_id)
                return 0
        _pcoll.load(key, path, 'IMAGE')
    return _pcoll[key].icon_id


def register():
    global _pcoll
    _pcoll = bpy.utils.previews.new()


def unregister():
    global _pcoll
    if _pcoll is not None:
        bpy.utils.previews.remove(_pcoll)
    _pcoll = None
    _failed.clear()
