"""Selected copied identities: scope, binding protection, cache cleanup and rollback."""
from pathlib import Path
import sys
import tempfile

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import OZO_Tools
from OZO_Tools import bone_identity as utility, rig_common as rig, rotation_follow as rf
from OZO_Tools.bone_parenting import edit_active_armature

OZO_Tools.register()


def fixture(label):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    obj = bpy.data.objects.new(label, bpy.data.armatures.new(label))
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    collection = obj.data.collections.new("Working")
    obj.data.collections.active = collection
    with edit_active_armature(bpy.context, obj) as bones:
        for i, name in enumerate(("Source", "Controller", "Other", "Properties")):
            bone = bones.new(name)
            bone.head, bone.tail = (i, 0, 0), (i, 1, 0)
            collection.assign(bone)
            bone["UserData"] = 0.42
    bpy.ops.object.mode_set(mode="POSE")
    settings = obj.data.ozo_rotation_follow
    settings.rotation_source = "Source"
    settings.property_bone = "Properties"
    select(obj, ["Controller"])
    rf.load_selected(bpy.context)
    return obj


def select(obj, names):
    if obj.mode == "EDIT":
        for bone in obj.data.edit_bones:
            bone.select = bone.select_head = bone.select_tail = bone.name in names
        obj.data.edit_bones.active = obj.data.edit_bones.get(names[0]) if names else None
    else:
        for pose in obj.pose.bones:
            pose.select = pose.name in names
        obj.data.bones.active = obj.data.bones.get(names[0]) if names else None


def copy_marker(obj, source, name):
    uid = obj.data.bones[source].get(rig.BONE_ID)
    with edit_active_armature(bpy.context, obj) as bones:
        old = bones[source]
        bone = bones.new(name)
        bone.head, bone.tail, bone.roll = old.head.copy(), old.tail.copy(), old.roll
        bone.parent = old.parent
        bone[rig.BONE_ID] = uid
        bone["UserData"] = 0.42
        for collection in old.collections:
            collection.assign(bone)


def geometry(obj):
    return {b.name: (b.parent.name if b.parent else None, rig.rest_geometry(b),
                     b.use_connect, b.use_deform, tuple(c.name for c in b.collections)) for b in obj.data.bones}


def reject(obj, fragment):
    before = {b.name: b.get(rig.BONE_ID) for b in obj.data.bones}
    records = obj.data.get(rf.RECORD_KEY)
    try:
        utility.clear_selected(bpy.context)
    except ValueError as error:
        assert fragment.lower() in str(error).lower(), str(error)
        print("Expected rejection:", error)
    else:
        raise AssertionError("Expected identity protection")
    assert before == {b.name: b.get(rig.BONE_ID) for b in obj.data.bones}
    assert obj.data.get(rf.RECORD_KEY) == records


# Unique, unbound preview controller: remove only the internal ID and stale row.
obj = fixture("Unbound")
settings = obj.data.ozo_rotation_follow
uid = obj.data.bones["Controller"][rig.BONE_ID]
before = geometry(obj)
assert bpy.ops.ozo.clear_selected_bone_identity() == {"FINISHED"}
assert rig.BONE_ID not in obj.data.bones["Controller"]
assert obj.data.bones["Controller"]["UserData"] == 0.42
assert not settings.affected
assert geometry(obj) == before
rf.load_selected(bpy.context)
assert obj.data.bones["Controller"][rig.BONE_ID] != uid

# Native copying of a marked source, as in the reported Master-controller case.
rf.connect_rotation(bpy.context)
old_records = obj.data[rf.RECORD_KEY]
source_id = obj.data.bones["Source"][rig.BONE_ID]
copy_marker(obj, "Source", "Master")
select(obj, ["Master"])
settings.rotation_source = "Master"
settings.rotation_source_id, settings.rotation_source_label = source_id, "Master"
reject(obj, "Choose Original Bone = Source")
obj.data.ozo_bone_identity.original_bone = "Source"
before = geometry(obj)
assert bpy.ops.ozo.clear_selected_bone_identity() == {"FINISHED"}
assert obj.data.bones["Source"][rig.BONE_ID] == source_id
assert rig.BONE_ID not in obj.data.bones["Master"]
assert obj.data[rf.RECORD_KEY] == old_records
assert not settings.rotation_source_id and not settings.rotation_source_label
assert geometry(obj) == before
rig.index_bones(obj.data)
select(obj, ["Controller"])
rf.load_selected(bpy.context)
rf.connect_rotation(bpy.context)
assert obj.data.bones["Master"][rig.BONE_ID] != source_id
record = next(iter(rf.read_records(obj.data)["bindings"].values()))
assert record["source"] == obj.data.bones["Master"][rig.BONE_ID]

# A unique identity belonging to an actual binding cannot be cleared.
select(obj, ["Controller"])
reject(obj, "owns an existing mechanism")
select(obj, ["Master"])
reject(obj, "owns an existing mechanism")

# Selecting the real source instead of its copy must not redirect the old binding.
copy_marker(obj, "Master", "AnotherMaster")
select(obj, ["Master"])
obj.data.ozo_bone_identity.original_bone = "AnotherMaster"
reject(obj, "does not point")
select(obj, ["AnotherMaster"])
obj.data.ozo_bone_identity.original_bone = "Master"
utility.clear_selected(bpy.context)

# Multiple copies of one bound original can be cleared together, in Edit Mode.
copy_marker(obj, "Master", "CopyA")
copy_marker(obj, "Master", "CopyB")
bpy.ops.object.mode_set(mode="EDIT")
select(obj, ["CopyA", "CopyB"])
assert bpy.ops.ozo.clear_selected_bone_identity() == {"FINISHED"}
assert obj.mode == "EDIT"
assert rig.BONE_ID not in obj.data.edit_bones["CopyA"] and rig.BONE_ID not in obj.data.edit_bones["CopyB"]
assert obj.data.edit_bones["Master"][rig.BONE_ID]
bpy.ops.object.mode_set(mode="POSE")

# Property-holder copies: old drivers continue targeting the original property.
settings = obj.data.ozo_rotation_follow
select(obj, ["Controller"])
rf.connect_property(bpy.context)
old_property_id = obj.data.bones["Properties"][rig.BONE_ID]
copy_marker(obj, "Properties", "NewProperties")
select(obj, ["NewProperties"])
obj.data.ozo_bone_identity.original_bone = "Properties"
old_driver = [(c.data_path, c.driver.expression) for c in obj.animation_data.drivers]
utility.clear_selected(bpy.context)
assert obj.data.bones["Properties"][rig.BONE_ID] == old_property_id
assert old_driver == [(c.data_path, c.driver.expression) for c in obj.animation_data.drivers]
assert obj.pose.bones["Properties"][settings.new_property] == 1

# A source that is also the original MCH parent, plus a copied generated MCH.
obj = fixture("MCHCopies")
with edit_active_armature(bpy.context, obj) as bones:
    bones["Controller"].parent = bones["Source"]
settings = obj.data.ozo_rotation_follow
settings.mode = "MCH"
rf.create_mch(bpy.context)
rf.connect_rotation(bpy.context)
copy_marker(obj, "Source", "NewMaster")
select(obj, ["NewMaster"])
obj.data.ozo_bone_identity.original_bone = "Source"
utility.clear_selected(bpy.context)
rf.connect_rotation(bpy.context)
copy_marker(obj, "MCH_ROT_Controller", "NewMCHController")
select(obj, ["NewMCHController"])
obj.data.ozo_bone_identity.original_bone = "MCH_ROT_Controller"
raw = obj.data[rf.RECORD_KEY]
utility.clear_selected(bpy.context)
assert obj.data[rf.RECORD_KEY] == raw
assert obj.data.bones["Controller"].parent.name == "MCH_ROT_Controller"
rf.connect_rotation(bpy.context)

# Batch failure restores cleared IDs, names/caches and preview rows.
obj = fixture("Rollback")
rig.identity(obj.data.bones["Other"])
select(obj, ["Controller", "Other"])
rf.load_selected(bpy.context)
before_ids = {b.name: b.get(rig.BONE_ID) for b in obj.data.bones}
before_preview = utility.settings_snapshot(obj.data)
old_clear = utility.clear_identity
calls = 0
def fail_clear(bone):
    global calls
    calls += 1
    old_clear(bone)
    if calls == 2:
        raise RuntimeError("Injected identity failure")
utility.clear_identity = fail_clear
try:
    utility.clear_selected(bpy.context)
except RuntimeError as error:
    assert "Injected" in str(error)
else:
    raise AssertionError("Expected injected failure")
utility.clear_identity = old_clear
assert {b.name: b.get(rig.BONE_ID) for b in obj.data.bones} == before_ids
assert utility.settings_snapshot(obj.data) == before_preview

# Native Undo/Redo and persistence, with no blend save by the tool itself.
label = obj.name
before = {b.name: b.get(rig.BONE_ID) for b in obj.data.bones}
bpy.context.preferences.edit.use_global_undo = True
bpy.ops.ed.undo_push(message="Before Clear Bone Identity")
assert bpy.ops.ozo.clear_selected_bone_identity() == {"FINISHED"}
bpy.ops.ed.undo_push(message="After Clear Bone Identity")
bpy.ops.ed.undo()
obj = bpy.data.objects[label]
assert {b.name: b.get(rig.BONE_ID) for b in obj.data.bones} == before
assert len(obj.data.ozo_rotation_follow.affected) == 2
bpy.ops.ed.redo()
obj = bpy.data.objects[label]
assert rig.BONE_ID not in obj.data.bones["Controller"] and rig.BONE_ID not in obj.data.bones["Other"]
assert not obj.data.ozo_rotation_follow.affected
with tempfile.TemporaryDirectory(prefix="bone_identity_", dir=ROOT / "tests") as directory:
    path = str(Path(directory) / "cleared.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    obj = bpy.context.active_object
    assert rig.BONE_ID not in obj.data.bones["Controller"]
    rf.load_selected(bpy.context)
    assert len(obj.data.ozo_rotation_follow.affected) == 2

OZO_Tools.unregister()
assert not hasattr(bpy.types.Armature, "ozo_bone_identity")
print("OZO_BONE_IDENTITY_PASS: unbound/copy scope, explicit original, binding/property protection, preview/cache cleanup, rollback, edit mode, Undo/Redo and persistence")
