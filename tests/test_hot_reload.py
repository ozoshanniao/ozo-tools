"""Exercise real extension ZIP install and reload in a disposable Blender session."""
from pathlib import Path
import sys
import tempfile
import zipfile

import bpy
import addon_utils

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))
from hot_reload import start
from zip_build import snapshot


with tempfile.TemporaryDirectory(prefix="hot_reload_test_", dir=ROOT / "tests") as directory:
    temporary = Path(directory).resolve()
    assert temporary.is_relative_to((ROOT / "tests").resolve())
    source = temporary / "source"
    for name, content in snapshot(ROOT / "OZO_Tools").items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    watcher = start(source, temporary / "runtime", watch=False)
    initial_scene_count = len(bpy.data.scenes)
    assert watcher.target.is_relative_to(temporary)
    assert hasattr(bpy.types.Scene, "ozo_bone_constraints")
    assert hasattr(bpy.types.Scene, "ozo_animation_scale")
    # Keep a real intermediate Rotation Follow mechanism across a full module reload.
    obj = bpy.data.objects.new("ReloadFollow", bpy.data.armatures.new("ReloadFollow"))
    bpy.context.scene.collection.objects.link(obj)
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    collection = obj.data.collections.new("Working")
    obj.data.collections.active = collection
    bpy.ops.object.mode_set(mode="EDIT")
    for name, x in (("ReloadSource", 0), ("ReloadControl", 2)):
        bone = obj.data.edit_bones.new(name)
        bone.head, bone.tail = (x, 0, 0), (x, 1, 0)
        bone.select = bone.select_head = bone.select_tail = name == "ReloadControl"
    bpy.ops.object.mode_set(mode="POSE")
    obj.pose.bones["ReloadSource"].select = False
    obj.pose.bones["ReloadControl"].select = True
    obj.data.ozo_rotation_follow.rotation_source = "ReloadSource"
    obj.data.ozo_rotation_follow.mode = "MCH"
    assert bpy.ops.ozo.follow_load_selected() == {"FINISHED"}
    assert bpy.ops.ozo.follow_create_mch() == {"FINISHED"}
    saved_follow_records = obj.data["ozo_rotation_follow_records"]
    # Arm stops after Switch, reloads all modules, then continues with stage 2.
    arm_obj = bpy.data.objects.new("ReloadArm", bpy.data.armatures.new("ReloadArm"))
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    work = arm_obj.data.collections.new("Working")
    arm_obj.data.collections.active = work
    bpy.ops.object.mode_set(mode="EDIT")
    for i, name in enumerate(("ROOT", "ORG_Arm.L", "ORG_Forearm.L", "ORG_Hand.L", "Arm_Tweak.L", "Forearm_Tweak.L", "Hand_Tweak.L", "Hand_Tip.L")):
        bone = arm_obj.data.edit_bones.new(name)
        bone.head, bone.tail = ((0, i-1, 0), (0, i, 0)) if i < 4 else ((1,i,0),(1,i+0.3,0))
    bpy.ops.object.mode_set(mode="POSE")
    arm_settings = arm_obj.data.ozo_arm
    for role in ("arm", "forearm", "hand"):
        setattr(arm_settings, "source_"+role, "ORG_"+role.title()+".L")
        setattr(arm_settings, "tweak_"+role, role.title()+"_Tweak.L")
    arm_settings.tip = "Hand_Tip.L"
    arm_settings.parent_mode, arm_settings.switch_parent = "BONE", "ROOT"
    assert bpy.ops.ozo.arm_switch() == {"FINISHED"}
    saved_arm_records = arm_obj.data["ozo_arm_records"]
    bpy.ops.object.mode_set(mode="OBJECT")
    arm_obj.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="POSE")
    assert watcher.tick(now=0) == 0.5
    submodule = watcher.module + ".bone_constraints"
    initial_module = sys.modules[submodule]
    original = (source / "bone_constraints.py").read_bytes()
    modified = original + b"\nHOT_RELOAD_TEST_VALUE = 1\n"
    (source / "bone_constraints.py").write_bytes(modified)
    watcher.tick(now=1)
    watcher.tick(now=2)
    assert watcher.reload_count == 1
    assert sys.modules[submodule] is not initial_module
    assert sys.modules[submodule].HOT_RELOAD_TEST_VALUE == 1
    assert obj.data["ozo_rotation_follow_records"] == saved_follow_records
    assert arm_obj.data["ozo_arm_records"] == saved_arm_records
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="POSE")
    assert bpy.ops.ozo.arm_chains() == {"FINISHED"}
    assert "Arm_FK.L" in arm_obj.data.bones and "MCH_IK_Hand.L" in arm_obj.data.bones
    bpy.ops.object.mode_set(mode="OBJECT")
    arm_obj.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="POSE")
    assert len(obj.data.ozo_rotation_follow.affected) == 1
    assert bpy.ops.ozo.follow_connect_rotation() == {"FINISHED"}
    assert len(obj.pose.bones["MCH_ROT_ReloadControl"].constraints) == 1
    assert hasattr(bpy.types.Scene, "ozo_bone_constraints")
    assert bpy.ops.ozo.sync_bone_constraints() == {"FINISHED"}
    # Same byte length, rapid edit: stale bytecode must not hide the change.
    (source / "bone_constraints.py").write_bytes(modified.replace(b"VALUE = 1", b"VALUE = 2"))
    added = source / "added_module.py"
    added.write_text("VALUE = 123\n", encoding="utf-8")
    watcher.tick(now=3)
    watcher.tick(now=4)
    assert watcher.reload_count == 2
    assert sys.modules[submodule].HOT_RELOAD_TEST_VALUE == 2
    assert (watcher.target / "added_module.py").is_file()
    # Invalid syntax leaves the registered add-on working.
    (source / "bone_constraints.py").write_bytes(b"def invalid syntax:\n")
    watcher.tick(now=5)
    assert not watcher.stopped
    assert watcher.reload_count == 2
    assert sys.modules[submodule].HOT_RELOAD_TEST_VALUE == 2
    assert addon_utils.check(watcher.module)[1]
    # A corrected save resumes and a deleted source file is removed.
    (source / "bone_constraints.py").write_bytes(original)
    added.unlink()
    watcher.tick(now=6)
    watcher.tick(now=7)
    assert watcher.reload_count == 3
    assert hasattr(bpy.types.Scene, "ozo_animation_scale")
    assert not (watcher.target / "added_module.py").exists()
    assert not hasattr(sys.modules[submodule], "HOT_RELOAD_TEST_VALUE")
    assert len(bpy.data.scenes) == initial_scene_count
    assert not bpy.context.preferences.use_preferences_save
    archive = watcher.session / "development.zip"
    with zipfile.ZipFile(archive) as package:
        assert "blender_manifest.toml" in package.namelist()
        assert not any("__pycache__" in name for name in package.namelist())
    manifest = source / "blender_manifest.toml"
    manifest.write_text(manifest.read_text("utf-8") + "\n# manifest edit\n", encoding="utf-8")
    watcher.tick(now=8)
    assert watcher.tick(now=9) is None
    assert watcher.stopped
    assert watcher.reload_count == 3
    addon_utils.disable(watcher.module, default_set=True)
    assert not hasattr(bpy.types.Scene, "ozo_animation_scale")
    assert not hasattr(bpy.types.Armature, "ozo_rotation_follow")
    assert not hasattr(bpy.types.Armature, "ozo_arm")
    bpy.context.preferences.extensions.repos.remove(watcher.repository)

print("OZO_HOT_RELOAD_PASS: ZIP install, child modules, same-size edits, syntax recovery, add/delete, manifest guard")
