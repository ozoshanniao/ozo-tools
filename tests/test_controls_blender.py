"""Verify generated hierarchy, actual FK/Tweak motion, clean controls and rollback."""
from pathlib import Path
import json
import sys
import tempfile

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import OZO_Tools
from OZO_Tools import bone_controls as controls
from OZO_Tools.bone_parenting import edit_active_armature

OZO_Tools.register()


def rig(label, side=".L", count=3):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    obj = bpy.data.objects.new(label, bpy.data.armatures.new(label))
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    sources = obj.data.collections.new("Sources")
    work = obj.data.collections.new("Working")
    tweaks = obj.data.collections.new("Existing Tweaks", parent=work)
    fks = obj.data.collections.new("Existing FK")
    obj.data.collections.active = work
    names = [f"ORG_{label}_{i+1:02}{side}.001" for i in range(count)]
    with edit_active_armature(bpy.context, obj) as bones:
        root = bones.new("ROOT")
        root.head, root.tail = (0, 0, -1), (0, 0, 0)
        parent = root
        for i, name in enumerate(names):
            b = bones.new(name)
            b.head, b.tail, b.roll = (i, 0, 0), (i+1, 0, 0), i * 0.17
            b.parent = parent
            b.use_connect = i > 0
            sources.assign(b)
            parent = b
    bpy.ops.object.mode_set(mode="POSE")
    select(obj, names)
    return obj, names


def select(obj, names):
    if obj.mode == "EDIT":
        for bone in obj.data.edit_bones:
            bone.select = bone.select_head = bone.select_tail = bone.name in names
        obj.data.edit_bones.active = obj.data.edit_bones[names[0]] if names else None
    else:
        for pose in obj.pose.bones:
            pose.select = pose.name in names
        obj.data.bones.active = obj.data.bones[names[0]] if names else None


def snapshot(obj):
    return {b.name: (b.parent.name if b.parent else None, b.use_connect,
                     tuple(b.head_local), tuple(b.tail_local), tuple(tuple(r) for r in b.matrix_local),
                     b.use_deform, b.get(controls.ID_KEY), tuple(c.name for c in b.collections))
            for b in obj.data.bones}


def expect_error(fn, obj):
    mode = obj.mode
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="OBJECT")
    before, raw = snapshot(obj), obj.data.get(controls.RECORD_KEY)
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")
    try:
        fn()
    except (ValueError, RuntimeError) as error:
        print("Expected rejection:", error)
    else:
        raise AssertionError("Expected rejection")
    assert obj.mode == mode
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="OBJECT")
    assert snapshot(obj) == before
    assert obj.data.get(controls.RECORD_KEY) == raw
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")


def near(a, b, eps=3e-5):
    assert (Vector(a) - Vector(b)).length < eps, (tuple(a), tuple(b))


def endpoint_checks(obj, names, tweak_names, tip_name):
    bpy.context.view_layer.update()
    for i, name in enumerate(names):
        near(obj.pose.bones[name].head, obj.pose.bones[tweak_names[i]].head)
        near(obj.pose.bones[name].tail,
             obj.pose.bones[tweak_names[i+1] if i+1 < len(names) else tip_name].head)


# Pose Mode: custom length, existing nested collection, source keys/driver/constraint.
obj, names = rig("Stick")
source = obj.pose.bones[names[0]]
source.keyframe_insert("location", frame=1)
source.keyframe_insert("location", frame=10)
source.driver_add("scale", 2).driver.expression = "1.0"
source.constraints.new("LIMIT_LOCATION")
action = obj.animation_data.action
action_name = action.name
native = obj.pose.bones["ROOT"].constraints.new("STRETCH_TO")
native_defaults = {key: getattr(native, key) for key in ("volume", "keep_axis", "head_tail", "influence", "bulge")}
obj.pose.bones["ROOT"].constraints.remove(native)
settings = obj.data.ozo_bone_controls
settings.tweak_length = 0.03
settings.tweak_use_collection = True
settings.tweak_collection = "Existing Tweaks"
before = snapshot(obj)
assert bpy.ops.ozo.create_tweak() == {"FINISHED"}
assert obj.mode == "POSE"
assert set(controls.selected_names(bpy.context)) == set(names)
record = controls.read_records(obj.data)["chains"][0]
tweak_names = [e["tweak_name"] for e in record["entries"]]
tip_name = record["tip_name"]
assert len(obj.data.bones) == 8
for i, name in enumerate(names):
    bone = obj.data.bones[name]
    assert bone.parent.name == tweak_names[i] and not bone.use_connect
    assert bone.use_deform
    near(bone.head_local, before[name][2])
    near(bone.tail_local, before[name][3])
    tweak = obj.data.bones[tweak_names[i]]
    assert tweak.parent.name == "ROOT" and not tweak.use_deform
    assert abs(tweak.length - 0.03) < 1e-6
    near(tweak.tail_local - tweak.head_local, (0.03, 0, 0))
    assert max(abs(tweak.matrix_local[r][c] - before[name][4][r][c])
               for r in range(4) for c in range(4)) < 1e-5
    assert [c.name for c in tweak.collections] == ["Existing Tweaks"]
    constraint = next(c for c in obj.pose.bones[name].constraints if c.type == "STRETCH_TO")
    assert constraint.target == obj
    assert constraint.subtarget == (tweak_names[i+1] if i+1 < len(names) else tip_name)
    for key in ("volume", "keep_axis", "head_tail", "influence", "bulge"):
        assert getattr(constraint, key) == native_defaults[key], (key, getattr(constraint, key), native_defaults[key])
tip = obj.data.bones[tip_name]
near(tip.head_local, before[names[-1]][3])
assert tip.parent.name == "ROOT" and not tip.use_deform
assert abs(tip.length - 0.03) < 1e-6
endpoint_checks(obj, names, tweak_names, tip_name)
obj.pose.bones[tweak_names[1]].location.z = 0.2
endpoint_checks(obj, names, tweak_names, tip_name)
obj.pose.bones[tweak_names[1]].location.z = 0
expect_error(lambda: controls.create_tweak(bpy.context), obj)

# Failed mutation restores original hierarchies, metadata and generated bones.
real_make_control = controls.make_control
calls = 0
def failing_make(*args, **kwargs):
    global calls
    calls += 1
    if calls == 2:
        raise RuntimeError("Injected creation failure")
    return real_make_control(*args, **kwargs)
controls.make_control = failing_make
expect_error(lambda: controls.create_fk(bpy.context), obj)
controls.make_control = real_make_control

# Stable IDs survive renames and saving/reopening between the two buttons.
obj.data.bones[tweak_names[0]].name = "Renamed Tweak"
tweak_names[0] = "Renamed Tweak"
obj.data.bones[names[0]].name = "Renamed ORG"
names[0] = "Renamed ORG"
select(obj, [tweak_names[0]])
with tempfile.TemporaryDirectory(prefix="controls_", dir=ROOT / "tests") as directory:
    path = str(Path(directory) / "between_buttons.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    obj = bpy.context.active_object
    settings = obj.data.ozo_bone_controls
    assert abs(settings.tweak_length - 0.03) < 1e-6
    assert settings.tweak_collection == "Existing Tweaks"
    settings.fk_use_collection = True
    settings.fk_collection = "Existing FK"
    assert bpy.ops.ozo.create_fk() == {"FINISHED"}
    fks = [f"Stick_{i+1:02}.L" for i in range(3)]
    for i, name in enumerate(fks):
        bone = obj.data.bones[name]
        assert bone.parent.name == (fks[i-1] if i else "ROOT")
        assert bone.use_connect == (i > 0)
        assert not bone.use_deform
        assert [c.name for c in bone.collections] == ["Existing FK"]
        assert obj.data.bones[tweak_names[i]].parent == bone
        assert not obj.pose.bones[name].constraints
        near(bone.head_local, (i, 0, 0))
        near(bone.tail_local, (i+1, 0, 0))
        original_name = record["entries"][i]["name"]
        assert max(abs(bone.matrix_local[r][c] - before[original_name][4][r][c])
                   for r in range(4) for c in range(4)) < 1e-5
    assert obj.data.bones[tip_name].parent.name == fks[-1]
    assert len(obj.animation_data.drivers) == 1
    assert len(obj.pose.bones[names[0]].constraints) == 2
    assert obj.animation_data.action.name == action_name
    curves = [c for layer in obj.animation_data.action.layers for strip in layer.strips
              for bag in strip.channelbags for c in bag.fcurves]
    assert len(curves) == 3
    assert all('Renamed ORG' in c.data_path for c in curves)
    endpoint_checks(obj, names, tweak_names, tip_name)
    obj.pose.bones[fks[0]].rotation_mode = "XYZ"
    obj.pose.bones[fks[0]].rotation_euler.y = 0.4
    endpoint_checks(obj, names, tweak_names, tip_name)
    obj.pose.bones[tweak_names[1]].location.z = 0.15
    endpoint_checks(obj, names, tweak_names, tip_name)
    expect_error(lambda: controls.create_fk(bpy.context), obj)

# Edit Mode: multiple chains, single-bone chain, .R and no side, active collection.
obj, names = rig("Edit", ".R", 2)
bpy.ops.object.mode_set(mode="EDIT")
extra = obj.data.edit_bones.new("ORG_Single.002")
extra.head, extra.tail = (0, 2, 0), (0, 3, 0)
obj.data.ozo_bone_controls.tweak_length = 0.15
select(obj, names + [extra.name])
assert bpy.ops.ozo.create_tweak() == {"FINISHED"}
assert obj.mode == "EDIT"
assert len(controls.read_records(obj.data)["chains"]) == 2
assert bpy.ops.ozo.create_fk() == {"FINISHED"}
assert obj.mode == "EDIT"
bpy.ops.object.mode_set(mode="POSE")
for name in ["Edit_01_Tweak.R", "Edit_02_Tweak.R", "Edit_02_Tip_Tweak.R",
             "Single_Tweak", "Single_Tip_Tweak"]:
    b = obj.data.bones[name]
    assert abs(b.length - 0.15) < 1e-6
    assert [c.name for c in b.collections] == ["Working"]
for name in ["Edit_01.R", "Edit_02.R", "Single"]:
    assert [c.name for c in obj.data.bones[name].collections] == ["Working"]

# Bad inputs fail before creating bones or constraints.
obj, names = rig("Reject")
select(obj, [names[0], names[2]])
expect_error(lambda: controls.create_tweak(bpy.context), obj)
select(obj, names)
settings = obj.data.ozo_bone_controls
settings.tweak_use_collection = True
settings.tweak_collection = "Missing"
expect_error(lambda: controls.create_tweak(bpy.context), obj)
settings.tweak_use_collection = False
with edit_active_armature(bpy.context, obj) as bones:
    collision = bones.new("Reject_01_Tweak.L")
    collision.head, collision.tail = (0, 2, 0), (0, 3, 0)
select(obj, names)
expect_error(lambda: controls.create_tweak(bpy.context), obj)
with edit_active_armature(bpy.context, obj) as bones:
    bones.remove(bones["Reject_01_Tweak.L"])
    bones[names[2]].parent = bones[names[0]]
    bones[names[2]].use_connect = False
    bones[names[2]].head, bones[names[2]].tail = (1, 0, 0), (1, 1, 0)
select(obj, names)
expect_error(lambda: controls.create_tweak(bpy.context), obj)

# Whole-operation rollback after the first generated control in the Tweak stage.
obj, names = rig("Rollback")
calls = 0
controls.make_control = failing_make
expect_error(lambda: controls.create_tweak(bpy.context), obj)
controls.make_control = real_make_control
assert not any(p.constraints for p in obj.pose.bones)

# The rest length remains correct on a scaled armature.
obj, names = rig("Scaled")
obj.scale = (2, 2, 2)
assert bpy.ops.ozo.create_tweak() == {"FINISHED"}
record = controls.read_records(obj.data)["chains"][0]
endpoint_checks(obj, names, [e["tweak_name"] for e in record["entries"]], record["tip_name"])

# Bent chain, arbitrary roll and a Connected external root retain rest geometry.
obj, names = rig("Bent")
points = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (1, 1, 1)]
with edit_active_armature(bpy.context, obj) as bones:
    for name in names:
        bones[name].use_connect = False
    for i, name in enumerate(names):
        bones[name].head, bones[name].tail = points[i], points[i+1]
        bones[name].roll = 0.3 + i * 0.23
    for name in names:
        bones[name].use_connect = True
select(obj, names)
assert bpy.ops.ozo.create_tweak() == {"FINISHED"}
assert bpy.ops.ozo.create_fk() == {"FINISHED"}
record = controls.read_records(obj.data)["chains"][0]
assert obj.data.bones["Bent_01.L"].use_connect
endpoint_checks(obj, names, [e["tweak_name"] for e in record["entries"]], record["tip_name"])
obj.pose.bones["Bent_02.L"].rotation_mode = "XYZ"
obj.pose.bones["Bent_02.L"].rotation_euler.z = 0.5
endpoint_checks(obj, names, [e["tweak_name"] for e in record["entries"]], record["tip_name"])

obj, names = rig("MovedParent", count=1)
with edit_active_armature(bpy.context, obj) as bones:
    bones[names[0]].use_connect = True
select(obj, names)
assert bpy.ops.ozo.create_tweak() == {"FINISHED"}
with edit_active_armature(bpy.context, obj) as bones:
    bones["ROOT"].tail.z = 0.1
select(obj, names)
expect_error(lambda: controls.create_fk(bpy.context), obj)

for name in ["ORG_X.L.001", "ORG_X.001.L", "ORG_X.002.001.L"]:
    assert controls.base_name(name) == ("X", ".L")
assert controls.base_name("ORG-X.R") == ("X", ".R")
assert controls.base_name("ArbitraryName.L.001") == ("ArbitraryName", ".L")

# Sources are the current selection, never a prefix scan. Unselected ORG bones
# and even the selected chain's unselected tail stay alone.
for mode in ("POSE", "EDIT"):
    obj, names = rig("Selection" + mode, count=3)
    obj.data.bones[names[0]].name = "AnyName" + mode + ".001"
    names[0] = "AnyName" + mode + ".001"
    obj.data.bones[names[1]].name = "ORG-OtherName" + mode
    names[1] = "ORG-OtherName" + mode
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")
    select(obj, names[:2])
    assert set(controls.selected_names(bpy.context)) == set(names[:2])
    assert bpy.ops.ozo.create_tweak() == {"FINISHED"}
    assert obj.mode == mode
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="POSE")
    assert len(obj.data.bones) == 7
    untouched = obj.data.bones[names[2]]
    assert untouched.parent.name == names[1] and untouched.use_connect
    assert controls.ID_KEY not in untouched
    assert not obj.pose.bones[names[2]].constraints
    assert bpy.ops.ozo.create_fk() == {"FINISHED"}
    assert "AnyName" + mode in obj.data.bones
    assert "OtherName" + mode in obj.data.bones
    select(obj, [])
    expect_error(lambda: controls.create_tweak(bpy.context), obj)
    assert "org_prefix" not in obj.data.ozo_bone_controls.bl_rna.properties

# In multi-object Edit Mode, bones selected on a second rig are excluded.
main, main_names = rig("ActiveOnly", count=1)
other, other_names = rig("OtherSelected", count=1)
bpy.ops.object.mode_set(mode="OBJECT")
main.select_set(True)
other.select_set(True)
bpy.context.view_layer.objects.active = main
other_before = snapshot(other)
bpy.ops.object.mode_set(mode="EDIT")
select(main, main_names)
for bone in other.data.edit_bones:
    bone.select = bone.select_head = bone.select_tail = True
assert controls.selected_names(bpy.context) == main_names
assert bpy.ops.ozo.create_tweak() == {"FINISHED"}
assert main.mode == "EDIT" and other.mode == "EDIT"
bpy.ops.object.mode_set(mode="OBJECT")
assert snapshot(other) == other_before
assert len(main.data.bones) == 4
obj = main
OZO_Tools.unregister()
assert not hasattr(bpy.types.Armature, "ozo_bone_controls")
OZO_Tools.register()
assert len(controls.read_records(obj.data)["chains"]) == 1
OZO_Tools.unregister()
print("OZO_CONTROLS_PASS: hierarchy, motion, defaults, clean FK, names, collections, edit/pose, persistence, rejection, rollback")
