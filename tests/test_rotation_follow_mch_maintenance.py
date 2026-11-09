"""Synthetic acceptance for changing MCH length and recovering deleted parents."""
from pathlib import Path
import json
import sys
import tempfile

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import OZO_Tools
from OZO_Tools import rotation_follow as rf, rig_common as rig
from OZO_Tools.bone_parenting import edit_active_armature

OZO_Tools.register()


def fixture(label, count=2, linked=True):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj = bpy.data.objects.new(label, bpy.data.armatures.new(label))
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    collection = obj.data.collections.new("MCH Collection")
    obj.data.collections.active = collection
    names = [f"SkirtHlpA_{i+1}.L" for i in range(count)]
    with edit_active_armature(bpy.context, obj) as bones:
        source = bones.new("SkirtHlpA_0.L")
        source.head, source.tail = (0, -1, 0), (0, 0, 0)
        props = bones.new("Properties")
        props.head, props.tail = (-2, 0, 0), (-2, 1, 0)
        parent = source
        for i, name in enumerate(names):
            bone = bones.new(name)
            bone.head, bone.tail = (0, i, 0), (0, i + 1, 0)
            bone.parent = parent
            bone.use_connect = True
            collection.assign(bone)
            parent = bone
    bpy.ops.object.mode_set(mode="POSE")
    for pose in obj.pose.bones:
        pose.select = pose.name in names
    obj.data.bones.active = obj.data.bones[names[0]]
    settings = obj.data.ozo_rotation_follow
    settings.rotation_source = "SkirtHlpA_0.L"
    settings.mode = "MCH"
    settings.property_bone = "Properties"
    settings.auto_falloff = True
    rf.load_selected(bpy.context)
    rf.create_mch(bpy.context)
    rf.connect_rotation(bpy.context)
    if linked:
        rf.connect_property(bpy.context)
        obj.pose.bones["Properties"][settings.new_property] = 0.5
    obj.update_tag()
    bpy.context.view_layer.update()
    return obj, settings, names


def binding(obj, name):
    return rf.read_records(obj.data)["bindings"][obj.data.bones[name][rig.BONE_ID]]


def state(obj):
    return {b.name: {"parent": b.parent.name if b.parent else None, "connected": b.use_connect,
                     "geometry": rig.rest_geometry(b), "id": b.get(rig.BONE_ID),
                     "deform": b.use_deform, "collections": [c.name for c in b.collections]}
            for b in obj.data.bones}


def same_state(obj, before):
    after = state(obj)
    assert set(after) == set(before)
    for name, expected in before.items():
        assert rig.same_geometry(obj.data.bones[name], expected["geometry"]), name
        assert {k: v for k, v in after[name].items() if k != "geometry"} == {k: v for k, v in expected.items() if k != "geometry"}, name


def reject(obj, fn, expected):
    mode = obj.mode
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="OBJECT")
    before, raw = state(obj), obj.data[rf.RECORD_KEY]
    drivers = [(c.data_path, c.driver.expression) for c in obj.animation_data.drivers] if obj.animation_data else []
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")
    try:
        fn(bpy.context)
    except (ValueError, RuntimeError) as error:
        assert expected.lower() in str(error).lower(), str(error)
        print("Expected rejection:", error)
    else:
        raise AssertionError("Expected rejection")
    assert obj.mode == mode
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="OBJECT")
    same_state(obj, before)
    assert obj.data[rf.RECORD_KEY] == raw
    assert ([(c.data_path, c.driver.expression) for c in obj.animation_data.drivers] if obj.animation_data else []) == drivers
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")


def remove_mch(obj, name):
    uid = binding(obj, name)["mch"]
    owner = rig.index_bones(obj.data)[uid].name
    with edit_active_armature(bpy.context, obj) as bones:
        bones.remove(bones[owner])
    return uid


# Apply a new length while retaining manually adjusted axes and all bindings.
obj, settings, names = fixture("Length")
with edit_active_armature(bpy.context, obj) as bones:
    mch = bones["MCH_ROT_" + names[0]]
    mch.tail = mch.head + Vector((0, 0, 0.15))
    mch.roll = 0.43
original = state(obj)
raw = obj.data[rf.RECORD_KEY]
drivers = [(c.data_path, c.driver.expression) for c in obj.animation_data.drivers]
constraint_names = {p.name: [c.name for c in p.constraints] for p in obj.pose.bones}
settings.mch_length = 0.03
bpy.ops.object.mode_set(mode="EDIT")
assert bpy.ops.ozo.follow_update_mch_length() == {"FINISHED"}
assert obj.mode == "EDIT"
bpy.ops.object.mode_set(mode="POSE")
for name, saved in original.items():
    bone = obj.data.bones[name]
    if name.startswith("MCH_ROT_"):
        assert abs(bone.length - 0.03) < 1e-6
        assert max(abs(bone.matrix_local[i][j] - saved["geometry"]["matrix"][i][j]) for i in range(4) for j in range(4)) < 1e-5
    else:
        assert rig.same_geometry(bone, saved["geometry"])
    assert bone.get(rig.BONE_ID) == saved["id"]
assert obj.data[rf.RECORD_KEY] == raw
assert [(c.data_path, c.driver.expression) for c in obj.animation_data.drivers] == drivers
assert {p.name: [c.name for c in p.constraints] for p in obj.pose.bones} == constraint_names
rf.connect_rotation(bpy.context)
rf.update_mch_length(bpy.context)  # No duplicate structure on repeat.

# A connected user child would be moved by a resize, so reject the full batch.
with edit_active_armature(bpy.context, obj) as bones:
    child = bones.new("UserConnectedChild")
    child.parent = bones["MCH_ROT_" + names[-1]]
    child.head = child.parent.tail
    child.tail = child.head + Vector((0, 1, 0))
    child.use_connect = True
settings.mch_length = 0.15
reject(obj, rf.update_mch_length, "Connected children")

# Reproduce the reported workflow: delete a connected mechanism, then recover.
obj, settings, names = fixture("Recover")
old_record = dict(binding(obj, names[0]))
old_id = remove_mch(obj, names[0])
assert obj.data.bones[names[0]].parent.name == "SkirtHlpA_0.L"
reject(obj, rf.create_mch, "Recreate Missing")
untouched_name = "MCH_ROT_" + names[1]
untouched = rig.rest_geometry(obj.data.bones[untouched_name])
settings.mch_length = 0.06
assert bpy.ops.ozo.follow_recreate_missing_mch() == {"FINISHED"}
new_record = binding(obj, names[0])
assert new_record["id"] == old_record["id"] and new_record["mch"] != old_id
assert new_record["constraint"] is None and new_record["link"] == old_record["link"]
mch = obj.data.bones["MCH_ROT_" + names[0]]
assert obj.data.bones[names[0]].parent == mch and mch.parent.name == "SkirtHlpA_0.L"
assert abs(mch.length - 0.06) < 1e-6 and not mch.use_deform
assert not obj.pose.bones[mch.name].constraints
assert rig.same_geometry(obj.data.bones[untouched_name], untouched)
assert obj.pose.bones["Properties"][settings.new_property] == 0.5
rf.connect_rotation(bpy.context)
obj.update_tag()
bpy.context.view_layer.update()
for name in names:
    record = binding(obj, name)
    owner = rig.index_bones(obj.data)[record["mch"]]
    assert len(obj.pose.bones[owner.name].constraints) == 1
    constraint = obj.pose.bones[owner.name].constraints[0]
    assert abs(constraint.influence - record["base"] * 0.5) < 1e-5
assert len(obj.animation_data.drivers) == 2
before = state(obj)
rf.recreate_missing_mch(bpy.context)
same_state(obj, before)

# Save/reopen a missing-MCH intermediate and continue recovery afterward.
remove_mch(obj, names[0])
with tempfile.TemporaryDirectory(prefix="mch_recover_", dir=ROOT / "tests") as directory:
    path = str(Path(directory) / "missing.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    obj = bpy.context.active_object
    settings = obj.data.ozo_rotation_follow
    rf.recreate_missing_mch(bpy.context)
    rf.connect_rotation(bpy.context)
    assert len(obj.animation_data.drivers) == 2

# Same-name replacements and changed controllers are never silently adopted.
obj, settings, names = fixture("Replacement", linked=False)
remove_mch(obj, names[0])
with edit_active_armature(bpy.context, obj) as bones:
    user = bones.new("MCH_ROT_" + names[0])
    user.head, user.tail = (3, 0, 0), (3, 1, 0)
reject(obj, rf.recreate_missing_mch, "already exists")
with edit_active_armature(bpy.context, obj) as bones:
    bones.remove(bones["MCH_ROT_" + names[0]])
    bones[names[0]].tail.x += 0.1
reject(obj, rf.recreate_missing_mch, "rest geometry changed")
obj, settings, names = fixture("Reparented", linked=False)
remove_mch(obj, names[0])
with edit_active_armature(bpy.context, obj) as bones:
    bones[names[0]].parent = None
reject(obj, rf.recreate_missing_mch, "current parent differs")

# Rebuild failures roll back only the newly attempted MCHs and record changes.
obj, settings, names = fixture("RecoveryRollback")
for name in names:
    remove_mch(obj, name)
old_insert = rig.insert_mch_parents
def failing_insert(*args, **kwargs):
    old_insert(*args, **kwargs)
    raise RuntimeError("Injected recovery failure")
rig.insert_mch_parents = failing_insert
reject(obj, rf.recreate_missing_mch, "Injected recovery failure")
rig.insert_mch_parents = old_insert

# Native Undo/Redo restores the missing state and the previous MCH length.
obj, settings, names = fixture("MaintenanceUndo", count=1)
label = obj.name
bpy.context.preferences.edit.use_global_undo = True
settings.mch_length = 0.12
bpy.ops.ed.undo_push(message="Before MCH Length")
assert bpy.ops.ozo.follow_update_mch_length() == {"FINISHED"}
bpy.ops.ed.undo_push(message="After MCH Length")
bpy.ops.ed.undo()
obj = bpy.data.objects[label]
assert abs(obj.data.bones["MCH_ROT_" + names[0]].length - 0.3) < 1e-6
bpy.ops.ed.redo()
obj = bpy.data.objects[label]
assert abs(obj.data.bones["MCH_ROT_" + names[0]].length - 0.12) < 1e-6
remove_mch(obj, names[0])
missing_record = obj.data[rf.RECORD_KEY]
bpy.ops.ed.undo_push(message="Before MCH Recovery")
assert bpy.ops.ozo.follow_recreate_missing_mch() == {"FINISHED"}
bpy.ops.ed.undo_push(message="After MCH Recovery")
bpy.ops.ed.undo()
obj = bpy.data.objects[label]
assert "MCH_ROT_" + names[0] not in obj.data.bones and obj.data[rf.RECORD_KEY] == missing_record
bpy.ops.ed.redo()
obj = bpy.data.objects[label]
assert "MCH_ROT_" + names[0] in obj.data.bones
assert binding(obj, names[0])["constraint"] is None
rf.connect_rotation(bpy.context)
assert len(obj.animation_data.drivers) == 1

OZO_Tools.unregister()
print("OZO_ROTATION_FOLLOW_MCH_MAINTENANCE_PASS: length, manual axes, binding preservation, deleted-parent recovery, property relink, saved stage, conflicts, rollback, Undo/Redo")
