"""Turn raw Kitsu records into flat task rows with a local folder path.

Folder layout, relative to the root folder set in the add-on:

    <project>/shots/<episode>/<sequence>/<shot>/<task_type>/
    <project>/assets/<asset_type>/<asset>/<task_type>/
    <project>/sequences/<episode>/<sequence>/<task_type>/     (sequence-level tasks)
    <project>/episodes/<episode>/<task_type>/                 (episode-level tasks)
    <project>/<entity_type>/<entity>/<task_type>/             (anything else, e.g. concepts)

The episode level is left out for projects without episodes (feature films).
Kept free of bpy so it can be tested outside Blender.
"""

import os
import re
from dataclasses import dataclass, field

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name) -> str:
    name = _BAD_CHARS.sub("_", str(name or "")).strip().rstrip(".")
    return name or "_unnamed"


@dataclass
class TaskRow:
    task_id: str
    project_id: str
    project_name: str
    kind: str            # SHOT, ASSET, SEQUENCE, EPISODE, OTHER
    entity_id: str
    entity_name: str
    context: str         # e.g. "E01 / SQ01" or "Character"
    task_type: str
    task_status_id: str
    status: str
    status_done: bool
    assigned_to_me: bool
    path_parts: list = field(default_factory=list)

    @property
    def rel_path(self) -> str:
        return os.path.join(*self.path_parts)

    @property
    def label(self) -> str:
        return f"{self.context} / {self.entity_name}" if self.context else self.entity_name


def _index(items):
    return {i["id"]: i for i in items or []}


def collect_tasks(client, only_mine=True, projects=None):
    """Fetch the tasks of the given projects (default: all open ones) as TaskRows."""
    me = (client.user or {}).get("id")
    task_types = _index(client.task_types())
    statuses = _index(client.task_statuses())
    asset_types = _index(client.asset_types())
    entity_types = _index(client.entity_types())

    rows = []
    for project in (projects if projects is not None else client.open_projects()):
        pid = project["id"]
        tasks = client.project_tasks(pid)
        if only_mine:
            tasks = [t for t in tasks if me in (t.get("assignees") or [])]
        if not tasks:
            continue

        episodes = _index(client.episodes(pid))
        sequences = _index(client.sequences(pid))
        shots = _index(client.shots(pid))
        assets = _index(client.assets(pid))
        others = {}
        proj = safe_name(project["name"])

        for t in tasks:
            eid = t["entity_id"]
            ttype = task_types.get(t["task_type_id"], {}).get("name", "task")
            status = statuses.get(t["task_status_id"], {})

            if eid in shots:
                shot = shots[eid]
                seq = sequences.get(shot.get("parent_id"))
                ep = episodes.get(seq.get("parent_id")) if seq else None
                ctx = [n for n in (ep and ep["name"], seq and seq["name"]) if n]
                kind, name = "SHOT", shot["name"]
                parts = [proj, "shots", *map(safe_name, ctx or ["_no_sequence"]), safe_name(name)]
            elif eid in assets:
                asset = assets[eid]
                atype = asset_types.get(asset.get("entity_type_id"), {}).get("name", "Asset")
                ctx = [atype]
                kind, name = "ASSET", asset["name"]
                parts = [proj, "assets", safe_name(atype), safe_name(name)]
            elif eid in sequences:
                seq = sequences[eid]
                ep = episodes.get(seq.get("parent_id"))
                ctx = [ep["name"]] if ep else []
                kind, name = "SEQUENCE", seq["name"]
                parts = [proj, "sequences", *map(safe_name, ctx), safe_name(name)]
            elif eid in episodes:
                ctx, kind, name = [], "EPISODE", episodes[eid]["name"]
                parts = [proj, "episodes", safe_name(name)]
            else:
                if eid not in others:
                    others[eid] = client.entity(eid)
                ent = others[eid] or {}
                etype = entity_types.get(ent.get("entity_type_id"), {}).get("name", "Other")
                ctx, kind, name = [etype], "OTHER", ent.get("name", eid[:8])
                parts = [proj, safe_name(etype.lower()), safe_name(name)]

            rows.append(TaskRow(
                task_id=t["id"],
                project_id=pid,
                project_name=project["name"],
                kind=kind,
                entity_id=eid,
                entity_name=name,
                context=" / ".join(ctx),
                task_type=ttype,
                task_status_id=t["task_status_id"],
                status=status.get("short_name", "?"),
                status_done=bool(status.get("is_done")),
                assigned_to_me=me in (t.get("assignees") or []),
                path_parts=parts + [safe_name(ttype)],
            ))

    order = {"ASSET": 0, "EPISODE": 1, "SEQUENCE": 2, "SHOT": 3, "OTHER": 4}
    rows.sort(key=lambda r: (r.project_name, order[r.kind], r.context, r.entity_name, r.task_type))
    return rows


def build_folders(root, rel_paths):
    """Create the given folders under root. Returns how many were newly created."""
    created = 0
    for rel in rel_paths:
        path = os.path.join(root, rel)
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            created += 1
    return created


_VERSION_RE = re.compile(r"_v(\d+)\.blend$", re.IGNORECASE)


def list_blend_files(folder):
    """Return [(filename, version_or_None, mtime)] for .blend files, newest version first."""
    if not os.path.isdir(folder):
        return []
    out = []
    for f in os.listdir(folder):
        if f.lower().endswith(".blend"):
            m = _VERSION_RE.search(f)
            out.append((f, int(m.group(1)) if m else None,
                        os.path.getmtime(os.path.join(folder, f))))
    out.sort(key=lambda x: (x[1] is not None, x[1] or 0, x[2]), reverse=True)
    return out


def _name_part(s) -> str:
    return re.sub(r"\s+", "-", safe_name(s))


def version_filename(project, entity, task_type, version) -> str:
    """Proj_entity_task_v001.blend, e.g. DEV_SH-0001_Animation_v001.blend"""
    return f"{_name_part(project)}_{_name_part(entity)}_{_name_part(task_type)}_v{version:03d}.blend"


def next_version(folder) -> int:
    versions = [v for _f, v, _m in list_blend_files(folder) if v is not None]
    return max(versions, default=0) + 1
