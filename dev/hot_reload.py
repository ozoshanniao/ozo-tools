"""Private ZIP-installed Blender development session, with source-save reloads."""
from pathlib import Path
import importlib
import sys
import tempfile
import time
import tomllib
import traceback

import bpy
import addon_utils

DEV = Path(__file__).resolve().parent
sys.path.insert(0, str(DEV))
from zip_build import SOURCE, build, snapshot


def log(message):
    print(f"[OZO DEV] {message}", flush=True)


def fail(exception):
    raise exception


class Watcher:
    def __init__(self, source, session, repository, module, files):
        self.source = Path(source)
        self.session = Path(session).resolve()
        self.repository = repository
        self.module = module
        self.target = Path(sys.modules[module].__file__).resolve().parent
        if not self.target.is_relative_to(self.session):
            raise ValueError("Refusing to change an add-on outside the private dev session")
        self.active = files
        self.candidate = None
        self.changed_at = 0.0
        self.last_error = None
        self.stopped = False
        self.reload_count = 0

    def sync(self, files):
        # Only this private extension directory is writable by the reloader.
        for name in self.active.keys() - files.keys():
            path = (self.target / name).resolve()
            if not path.is_relative_to(self.target):
                raise ValueError("Path escaped the development extension")
            path.unlink(missing_ok=True)
        for name, content in files.items():
            path = (self.target / name).resolve()
            if not path.is_relative_to(self.target):
                raise ValueError("Path escaped the development extension")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        # Avoid stale bytecode after quick edits of identical size.
        for path in self.target.rglob("*.pyc"):
            if path.resolve().is_relative_to(self.target):
                path.unlink()

    def reload(self, files):
        addon_utils.disable(self.module, handle_error=fail)
        self.sync(files)
        for name in list(sys.modules):
            if name == self.module or name.startswith(self.module + "."):
                del sys.modules[name]
        importlib.invalidate_caches()
        module = addon_utils.enable(self.module, handle_error=fail)
        if module is None or not addon_utils.check(self.module)[1]:
            raise RuntimeError("New add-on failed to register")
        self.active = files
        self.reload_count += 1
        for screen in bpy.data.screens:
            for area in screen.areas:
                area.tag_redraw()
        log(f"Reloaded #{self.reload_count}: {self.module}")

    def tick(self, now=None):
        if self.stopped:
            return None
        if not addon_utils.check(self.module)[1]:
            log("Add-on disabled; watcher stopped. Restart the VS Code task to resume.")
            self.stopped = True
            return None
        try:
            files = snapshot(self.source)
        except Exception as exception:
            error = str(exception)
            if error != self.last_error:
                log(f"Source error; keeping the loaded version: {error}")
                self.last_error = error
            self.candidate = None
            return 0.5
        self.last_error = None
        if files == self.active:
            self.candidate = None
            return 0.5
        now = time.monotonic() if now is None else now
        if files != self.candidate:
            self.candidate = files
            self.changed_at = now
            return 0.5
        if now - self.changed_at < 0.8:
            return 0.5
        if files["blender_manifest.toml"] != self.active["blender_manifest.toml"]:
            log("Manifest changed; restart the VS Code task to reinstall the development ZIP.")
            self.stopped = True
            return None
        try:
            self.reload(files)
            self.candidate = None
        except Exception:
            # unregister/register can leave partially registered classes on failure.
            # Stop instead of guessing how to remove arbitrary Blender resources.
            traceback.print_exc()
            log("Reload failed; fix the code and restart this development Blender session.")
            self.stopped = True
            return None
        return 0.5


def start(source=SOURCE, runtime=DEV / ".runtime", watch=True):
    runtime = Path(runtime).resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix="session-", dir=runtime)).resolve()
    if not session.is_relative_to(runtime):
        raise ValueError("Invalid development session directory")
    archive = session / "development.zip"
    files = build(source, archive)
    manifest = tomllib.loads(files["blender_manifest.toml"].decode("utf-8"))
    bpy.context.preferences.use_preferences_save = False
    repository = bpy.context.preferences.extensions.repos.new(
        name="OZO Development (temporary)", module="ozo_dev",
        custom_directory=str(session / "repository"), remote_url="", source="USER",
    )
    result = bpy.ops.extensions.package_install_files(
        filepath=str(archive), repo=repository.module, enable_on_install=True,
    )
    module = f"bl_ext.{repository.module}.{manifest['id']}"
    if result != {"FINISHED"} or not addon_utils.check(module)[1]:
        raise RuntimeError("Development ZIP installation failed")
    watcher = Watcher(source, session, repository, module, files)
    if watch:
        bpy.app.timers.register(watcher.tick, first_interval=0.5, persistent=True)
    log(f"Watching: {source}")
    log(f"Private installed copy: {watcher.target}")
    log("Save source in VS Code; reload occurs after about 1-2 seconds.")
    return watcher


if __name__ == "__main__":
    _ozo_dev_watcher = start()
