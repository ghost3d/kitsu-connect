# Kitsu Connect

A Blender add-on (Blender 4.2+) that connects to a [Kitsu](https://www.cg-wire.com/kitsu) server,
lists your tasks, mirrors shots and assets as local folders, and saves versioned task files
that are recorded back in Kitsu.

## Features

- Log in with server address, email and password (password kept in memory unless you choose to remember it)
- Project selector and task list (only your tasks, or every task in the project)
- Local folder structure mirroring Kitsu, all under `Source/` so it never clashes with a
  Unity (or other engine) project in the same folder:
  - `<local>/<project>/Source/shots/<episode>/<sequence>/<shot>/<task_type>/`
  - `<local>/<project>/Source/assets/<asset_type>/<asset>/<task_type>/`
- Files named `Proj_entity_task_v###.blend`, e.g. `DEV_SH-0001_Animation_v001.blend`
- **Create First File** (from the current scene or a new scene) and **Version Up**
- Each version is recorded in Kitsu as a working file, a task comment and a preview revision with a viewport snapshot
- Creating, opening or versioning up a file sets the task to `wip` (only from todo, ready, neutral or retake)

## Install

Zip the folder contents and use Preferences → Get Extensions → Install from Disk, or add the
parent `blender` folder as a Script Directory in Preferences → File Paths.

The panel is in the 3D Viewport sidebar (N) under the **Kitsu** tab.
