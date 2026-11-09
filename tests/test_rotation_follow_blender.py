"""Synthetic-only Rotation Follow acceptance tests; never loads a user's character."""
from pathlib import Path
import json
import math
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
CASES = []


def fixture(label, count=3, source_child=False):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    obj = bpy.data.objects.new(label, bpy.data.armatures.new(label))
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    current = obj.data.collections.new("Working")
    obj.data.collections.new("Mechanisms", parent=current)
    obj.data.collections.active = current
    names = [f"Finger_{i+1:02}.L" for i in range(count)]
    with edit_active_armature(bpy.context, obj) as bones:
        for name, head, tail in (("ROOT", (0, 0, -1), (0, 0, 0)),
                                  ("Source", (-2, 0, 0), (-2, 1, 0)),
                                  ("Properties", (-3, 0, 0), (-3, 1, 0))):
            bone = bones.new(name)
            bone.head, bone.tail = head, tail
            current.assign(bone)
        parent = bones["ROOT"]
        for i, name in enumerate(names):
            bone = bones.new(name)
            bone.head, bone.tail = (0, i, 0), (0, i + 1, 0)
            bone.parent = parent
            bone.use_connect = True
            current.assign(bone)
            parent = bone
        if source_child:
            bones["Source"].parent = parent
    bpy.ops.object.mode_set(mode="POSE")
    settings = obj.data.ozo_rotation_follow
    settings.rotation_source = "Source"
    settings.property_bone = "Properties"
    select(obj, names)
    return obj, settings, names


def select(obj, names):
    if obj.mode == "EDIT":
        for bone in obj.data.edit_bones:
            bone.select = bone.select_head = bone.select_tail = bone.name in names
        obj.data.edit_bones.active = obj.data.edit_bones.get(names[0]) if names else None
    else:
        for pose in obj.pose.bones:
            pose.select = pose.name in names
        obj.data.bones.active = obj.data.bones.get(names[0]) if names else None


def structure(obj):
    return {bone.name: (bone.parent.name if bone.parent else None, bone.use_connect,
                        tuple(tuple(row) for row in bone.matrix_local), bone.length, bone.use_deform,
                        tuple(c.name for c in bone.collections), bone.get(rig.BONE_ID))
            for bone in obj.data.bones}


def binding(obj, name):
    uid = obj.data.bones[name][rig.BONE_ID]
    return rf.read_records(obj.data)["bindings"][uid]


def constraint(obj, name):
    record = binding(obj, name)
    index = rig.index_bones(obj.data)
    owner = index[record["mch"] or record["controlled"]]
    return obj.pose.bones[owner.name].constraints[record["constraint"]]


def bases(settings):
    return [round(item.base, 5) for item in settings.affected]


def reject(fn, obj, contains=None):
    mode = obj.mode
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="OBJECT")
    before = structure(obj)
    records = obj.data.get(rf.RECORD_KEY)
    curves = [(c.data_path, c.driver.expression) for c in (obj.animation_data.drivers if obj.animation_data else [])]
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")
    try:
        fn(bpy.context)
    except (ValueError, RuntimeError) as error:
        if contains:
            assert contains.lower() in str(error).lower(), str(error)
        print("Expected rejection:", error)
    else:
        raise AssertionError("Expected validation rejection")
    assert obj.mode == mode
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="OBJECT")
    assert structure(obj) == before
    assert obj.data.get(rf.RECORD_KEY) == records
    assert [(c.data_path, c.driver.expression) for c in (obj.animation_data.drivers if obj.animation_data else [])] == curves
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")


def evaluate(obj):
    # Tag ID properties explicitly, as a UI edit does, without stepping animation.
    obj.update_tag()
    bpy.context.view_layer.update()


obj, settings, names = fixture("Direct")
for name in names:
    pose = obj.pose.bones[name]
    pose.constraints.new("LIMIT_LOCATION").name = "Before"
    pose.constraints.new("STRETCH_TO").name = "Stretch First"
    pose.constraints.new("LIMIT_ROTATION").name = "Between"
    pose.constraints.new("STRETCH_TO").name = "Stretch Second"
assert bpy.ops.ozo.follow_load_selected() == {"FINISHED"}
assert bases(settings) == [1, 1, 1]
before = structure(obj)
assert bpy.ops.ozo.follow_connect_rotation() == {"FINISHED"}
assert structure(obj) == before
for name in names:
    c = constraint(obj, name)
    assert c.type == "COPY_ROTATION" and c.target == obj and c.subtarget == "Source"
    assert c.owner_space == c.target_space == "LOCAL" and c.mix_mode == "REPLACE"
    assert c.use_x and c.use_y and c.use_z and not (c.invert_x or c.invert_y or c.invert_z)
    assert c.influence == 1
    constraints = obj.pose.bones[name].constraints
    assert [x.name for x in constraints if x != c] == ["Before", "Stretch First", "Between", "Stretch Second"]
    assert list(constraints).index(c) == 1
rf.connect_rotation(bpy.context)
assert all(len(obj.pose.bones[name].constraints) == 5 for name in names)
CASES.append("Direct single/multiple bones, native defaults, before-Stretch ordering and idempotent update")

settings.auto_falloff = True
assert bases(settings) == [1, 1, 1]  # Toggling does not overwrite manual preview.
rf.apply_falloff(bpy.context)
assert bases(settings) == [0.2, 0.5, 0.8]
settings.affected[1].base = 0.35
settings.start_influence = 0.8
settings.end_influence = 0.2
assert bases(settings) == [0.2, 0.35, 0.8]
rf.connect_rotation(bpy.context)
assert abs(constraint(obj, names[1]).influence - 0.35) < 1e-6
rf.apply_falloff(bpy.context)
assert bases(settings) == [0.8, 0.5, 0.2]
settings.auto_falloff = False
assert bases(settings) == [1, 1, 1]
rf.connect_rotation(bpy.context)
assert all(constraint(obj, name).influence == 1 for name in names)
CASES.append("Falloff off/on, explicit recomputation, manual overrides, reverse and clearing hidden coefficients")

# Independent chains and a single bone, using topology rather than labels/length.
obj, settings, names = fixture("Chains")
with edit_active_armature(bpy.context, obj) as bones:
    for name, parent, head, tail in (("Unrelated_B", None, (2, 0, 0), (2, 5, 0)),
                                     ("Unrelated_A", "Unrelated_B", (2, 5, 0), (2, 5.1, 0)),
                                     ("Single", None, (4, 0, 0), (4, 1, 0))):
        b = bones.new(name)
        b.head, b.tail = head, tail
        b.parent = bones.get(parent) if parent else None
settings.auto_falloff = True
select(obj, names + ["Unrelated_A", "Single", "Unrelated_B"])
rf.load_selected(bpy.context)
by_name = {item.name: round(item.base, 5) for item in settings.affected}
assert by_name == {names[0]: 0.2, names[1]: 0.5, names[2]: 0.8,
                   "Unrelated_B": 0.2, "Unrelated_A": 0.8, "Single": 0.2}
select(obj, [names[0], names[2]])
reject(rf.load_selected, obj, "gap")
with edit_active_armature(bpy.context, obj) as bones:
    bones["Unrelated_B"].parent = bones[names[0]]
select(obj, names + ["Unrelated_B"])
reject(rf.load_selected, obj, "branches")
settings.auto_falloff = False
rf.load_selected(bpy.context)  # Independent/branching bones are allowed with no falloff.
CASES.append("Single bone, separate unequal-length chains, gaps/branches and no-falloff independent selection")

obj, settings, names = fixture("MCH")
settings.mode = "MCH"
settings.mch_length = 0.15
settings.specify_collection = True
settings.collection = "Mechanisms"
settings.auto_falloff = True
obj.pose.bones[names[0]].constraints.new("LIMIT_ROTATION")
obj.pose.bones[names[0]].keyframe_insert("rotation_quaternion", frame=1)
obj.pose.bones[names[0]].driver_add("scale", 2).driver.expression = "1.0"
obj.pose.bones[names[0]]["UserProperty"] = 0.4
rf.load_selected(bpy.context)
before = structure(obj)
assert bpy.ops.ozo.follow_create_mch() == {"FINISHED"}
for i, name in enumerate(names):
    mch = obj.data.bones["MCH_ROT_" + name]
    assert mch.parent.name == (names[i-1] if i else "ROOT")
    assert obj.data.bones[name].parent == mch and not obj.data.bones[name].use_connect
    actual = structure(obj)[name]
    assert max(abs(actual[2][r][c] - before[name][2][r][c]) for r in range(4) for c in range(4)) < 1e-5
    assert abs(actual[3] - before[name][3]) < 1e-5
    assert actual[4:6] == before[name][4:6]
    assert not mch.use_deform and abs(mch.length - 0.15) < 1e-6
    assert [c.name for c in mch.collections] == ["Mechanisms"]
    assert not obj.pose.bones[mch.name].constraints
    assert "UserProperty" not in obj.pose.bones[mch.name]
    assert "UserProperty" not in mch
assert len(obj.animation_data.drivers) == 1
rf.create_mch(bpy.context)
assert len(obj.data.bones) == 9

# A different source-axis frame, manual MCH roll/orientation/length and frozen list.
with edit_active_armature(bpy.context, obj) as bones:
    b = bones["MCH_ROT_" + names[1]]
    b.tail = b.head + Vector((1, 0, 0)) * 0.23
    b.roll = 0.43
select(obj, ["MCH_ROT_" + names[-1]])
manual = rig.rest_geometry(obj.data.bones["MCH_ROT_" + names[1]])
with tempfile.TemporaryDirectory(prefix="rotation_follow_", dir=ROOT / "tests") as directory:
    path = str(Path(directory) / "manual_stage.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    obj = bpy.context.active_object
    settings = obj.data.ozo_rotation_follow
    assert len(settings.affected) == 3
    assert bpy.ops.ozo.follow_connect_rotation() == {"FINISHED"}
    assert rig.same_geometry(obj.data.bones["MCH_ROT_" + names[1]], manual)
    for name in names:
        assert constraint(obj, name).id_data == obj
        assert constraint(obj, name).path_from_id().startswith('pose.bones["MCH_ROT_')
        assert not any(c.type == "COPY_ROTATION" for c in obj.pose.bones[name].constraints)
    assert len(obj.pose.bones[names[0]].constraints) == 1
    assert len(obj.animation_data.drivers) == 1
CASES.append("MCH insertion, clean data, rest preservation, orientation adjustment, fixed scope and saved intermediate stage")

# Real local-space rotation with a parent and controller-local animation still free.
obj, settings, names = fixture("Motion", count=1)
settings.mode = "MCH"
rf.load_selected(bpy.context)
rf.create_mch(bpy.context)
rf.connect_rotation(bpy.context)
source = obj.pose.bones["Source"]
source.rotation_mode = "XYZ"
source.rotation_euler.z = 0.4
evaluate(obj)
controlled = obj.pose.bones[names[0]]
owner = obj.pose.bones["MCH_ROT_" + names[0]]
assert abs(owner.matrix.to_euler().z - 0.4) < 1e-5
assert abs(controlled.matrix.to_euler().z - 0.4) < 1e-5
controlled.rotation_mode = "XYZ"
controlled.rotation_euler.z = 0.25
evaluate(obj)
assert abs(controlled.matrix.to_euler().z - 0.65) < 1e-5
obj.rotation_euler = (0.2, 0.3, 0.4)
obj.scale = (1.2, 0.8, 1.4)
evaluate(obj)
assert abs(controlled.matrix.to_euler().z - 0.65) < 1e-5
assert all(math.isfinite(v) for row in (obj.matrix_world @ controlled.matrix) for v in row)
CASES.append("Evaluated MCH follow, independent controller rotation, parented/local axes and rotated nonuniform object scale")

# Total-property behavior, including coefficient updates and persistence, in both modes.
for mode in ("DIRECT", "MCH"):
    obj, settings, names = fixture("Property" + mode)
    settings.mode = mode
    settings.auto_falloff = True
    rf.load_selected(bpy.context)
    if mode == "MCH":
        rf.create_mch(bpy.context)
    rf.connect_rotation(bpy.context)
    settings.connect_follow_property = True
    settings.new_property = "Follow.L"
    assert bpy.ops.ozo.follow_connect_property() == {"FINISHED"}
    props = obj.pose.bones["Properties"]
    assert isinstance(props["Follow.L"], float) and props["Follow.L"] == 1
    ui = props.id_properties_ui("Follow.L").as_dict()
    assert ui["min"] == 0 and ui["max"] == 1 and ui["default"] == 1
    for total in (0, 0.5, 1):
        props["Follow.L"] = float(total)
        evaluate(obj)
        for name, base in zip(names, (0.2, 0.5, 0.8)):
            assert abs(constraint(obj, name).influence - total * base) < 1e-5
    settings.affected[1].base = 0.37
    rf.connect_rotation(bpy.context)
    props["Follow.L"] = 0.5
    evaluate(obj)
    assert abs(constraint(obj, names[1]).influence - 0.185) < 1e-5
    settings.auto_falloff = False
    rf.connect_rotation(bpy.context)
    evaluate(obj)
    assert all(abs(constraint(obj, name).influence - 0.5) < 1e-5 for name in names)
    obj.data.bones["Properties"].name = "Renamed Property Bone"
    props = obj.pose.bones["Renamed Property Bone"]
    obj.data.bones["Source"].name = "Renamed Source"
    obj.data.bones[names[0]].name = "Renamed Controller"
    names[0] = "Renamed Controller"
    rf.connect_rotation(bpy.context)
    assert all(constraint(obj, name).subtarget == "Renamed Source" for name in names)
    with tempfile.TemporaryDirectory(prefix="follow_driver_", dir=ROOT / "tests") as directory:
        path = str(Path(directory) / "driver.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path)
        bpy.ops.wm.open_mainfile(filepath=path)
        obj = bpy.context.active_object
        settings = obj.data.ozo_rotation_follow
        obj.pose.bones["Renamed Property Bone"]["Follow.L"] = 0.25
        evaluate(obj)
        assert all(abs(constraint(obj, name).influence - 0.25) < 1e-5 for name in names)
        rf.connect_rotation(bpy.context)
        assert bpy.ops.ozo.follow_disconnect_property() == {"FINISHED"}
        assert "Follow.L" in obj.pose.bones["Renamed Property Bone"]
        assert all(constraint(obj, name).influence == 1 for name in names)
        assert not obj.animation_data.drivers
        # Existing property limits/animation/value are never rewritten.
        props = obj.pose.bones["Renamed Property Bone"]
        props["Existing"] = 0.6
        props.id_properties_ui("Existing").update(min=-2.0, max=2.0, default=0.6)
        props.keyframe_insert(data_path='["Existing"]', frame=1)
        old_ui = props.id_properties_ui("Existing").as_dict()
        settings.property_mode = "EXISTING"
        settings.property_bone = props.name
        settings.existing_property = "Existing"
        rf.connect_property(bpy.context)
        evaluate(obj)
        assert props.id_properties_ui("Existing").as_dict() == old_ui
        assert abs(props["Existing"] - 0.6) < 1e-6
        assert all(abs(constraint(obj, name).influence - 0.6) < 1e-5 for name in names)
CASES.append("Both modes: new/existing properties, totals 0/.5/1, updated bases, Auto Falloff off, renames, save/reopen and safe unlink")

# Validation and transactional recovery on real structures/constraints/drivers.
obj, settings, names = fixture("Cycle", source_child=True)
reject(rf.load_selected, obj, "cycle")
obj, settings, names = fixture("Self")
select(obj, names + ["Source"])
reject(rf.load_selected, obj, "also be affected")
obj, settings, names = fixture("Conflict")
rf.load_selected(bpy.context)
obj.pose.bones[names[-1]].constraints.new("COPY_ROTATION")
reject(rf.connect_rotation, obj, "user rotation")
assert all(not obj.pose.bones[name].constraints for name in names[:-1])
for c in list(obj.pose.bones[names[-1]].constraints):
    obj.pose.bones[names[-1]].constraints.remove(c)
rf.connect_rotation(bpy.context)
constraint(obj, names[0]).invert_x = True
reject(rf.connect_rotation, obj, "edited")
constraint(obj, names[0]).invert_x = False
constraint(obj, names[0]).driver_add("influence").driver.expression = "0.5"
reject(rf.connect_rotation, obj, "driv")
constraint(obj, names[0]).driver_remove("influence")
constraint(obj, names[0]).influence = 1
with edit_active_armature(bpy.context, obj) as bones:
    bones.remove(bones[names[-1]])
    replacement = bones.new(names[-1])
    replacement.head, replacement.tail = (3, 0, 0), (3, 1, 0)
reject(rf.connect_rotation, obj, "missing or replaced")
CASES.append("Source self-reference, descendant/constraint cycles, user mechanisms/drivers, edited constraints and same-name bone replacement")

# Inject a mid-constraint failure after a previous owned driver has been updated.
obj, settings, names = fixture("Rollback")
settings.auto_falloff = True
rf.load_selected(bpy.context)
rf.connect_rotation(bpy.context)
rf.connect_property(bpy.context)
old_write = rf.write_driver
calls = 0
def fail_driver(*args, **kwargs):
    global calls
    calls += 1
    old_write(*args, **kwargs)
    if calls == 2:
        raise RuntimeError("Injected driver-update failure")
rf.write_driver = fail_driver
settings.affected[0].base = 0.9
reject(rf.connect_rotation, obj, "Injected")
rf.write_driver = old_write
evaluate(obj)
assert abs(constraint(obj, names[0]).influence - 0.2) < 1e-5

# Fail after creating all MCHs; hierarchy, IDs and metadata return exactly.
obj, settings, names = fixture("MCHRollback")
settings.mode = "MCH"
rf.load_selected(bpy.context)
old_insert = rig.insert_mch_parents
def fail_mch(*args, **kwargs):
    old_insert(*args, **kwargs)
    raise RuntimeError("Injected MCH-insertion failure")
rig.insert_mch_parents = fail_mch
bpy.ops.object.mode_set(mode="EDIT")
reject(rf.create_mch, obj, "Injected")
rig.insert_mch_parents = old_insert
bpy.ops.object.mode_set(mode="POSE")
CASES.append("Injected partial driver and MCH failures restore hierarchy, IDs, metadata, drivers, mode and selection")

shared = bpy.data.objects.new("Shared", obj.data)
bpy.context.scene.collection.objects.link(shared)
assert not bpy.ops.ozo.follow_connect_rotation.poll()
reject(rf.connect_rotation, obj, "single-user")
bpy.data.objects.remove(shared, do_unlink=True)
obj.scale.x = 0
evaluate(obj)
reject(rf.connect_rotation, obj, "singular")
obj.scale.x = 1
evaluate(obj)

# Local-axis meaning is verified numerically after adjusting both rest frames.
for mode in ("DIRECT", "MCH"):
    obj, settings, names = fixture("Axes" + mode, count=1)
    with edit_active_armature(bpy.context, obj) as bones:
        bones["Source"].tail = bones["Source"].head + Vector((1, 0, 0))
        bones["Source"].roll = 0.2
        bones[names[0]].roll = 0.7
    select(obj, names)
    settings.mode = mode
    settings.auto_falloff = True
    settings.start_influence = 0.4
    rf.load_selected(bpy.context)
    if mode == "MCH":
        rf.create_mch(bpy.context)
        with edit_active_armature(bpy.context, obj) as bones:
            bone = bones["MCH_ROT_" + names[0]]
            bone.tail = bone.head + Vector((0, 0, 0.23))
            bone.roll = -0.35
    rf.connect_rotation(bpy.context)
    source = obj.pose.bones["Source"]
    source.rotation_mode = "XYZ"
    source.rotation_euler.z = 0.5
    obj.rotation_euler = (0.2, -0.4, 0.3)
    evaluate(obj)
    controlled = obj.pose.bones[names[0]]
    owner = obj.pose.bones["MCH_ROT_" + names[0]] if mode == "MCH" else controlled
    delta = owner.bone.matrix_local.inverted() @ owner.matrix
    assert abs(delta.to_euler().z - 0.2) < 1e-5, (mode, delta.to_euler()[:])
    # Under nonuniform object scale Blender's native local-space conversion
    # can introduce shear/axis coupling. Compare with a separately hand-built
    # native reference rather than incorrectly promising invariant Euler angles.
    owner_name = owner.name
    with edit_active_armature(bpy.context, obj) as bones:
        old = bones[owner_name]
        reference = bones.new("NativeReference")
        reference.head, reference.tail, reference.roll = old.head.copy(), old.tail.copy(), old.roll
        reference.parent = old.parent
    native = obj.pose.bones["NativeReference"].constraints.new("COPY_ROTATION")
    native.target, native.subtarget = obj, "Source"
    native.owner_space = native.target_space = "LOCAL"
    native.mix_mode = "REPLACE"
    native.influence = settings.affected[0].base
    obj.scale = (0.8, 1.2, 1.4)
    evaluate(obj)
    controlled = obj.pose.bones[names[0]]
    owner = obj.pose.bones[owner_name]
    reference = obj.pose.bones["NativeReference"]
    assert max(abs(owner.matrix[i][j] - reference.matrix[i][j]) for i in range(4) for j in range(4)) < 1e-5
    assert owner.bone.matrix_local.to_quaternion().rotation_difference(owner.matrix.to_quaternion()).angle > 0.05
    if mode == "MCH":
        controlled.rotation_mode = "XYZ"
        controlled.rotation_euler.x = 0.15
        evaluate(obj)
        expected = owner.matrix @ owner.bone.matrix_local.inverted() @ controlled.bone.matrix_local @ controlled.matrix_basis
        assert max(abs(expected[i][j] - controlled.matrix[i][j]) for i in range(4) for j in range(4)) < 1e-5
CASES.append("Numerical Direct/MCH local-axis tests with different rest axes, manually oriented MCHs and nonuniform world transforms")

# Preview reorder is topological after Auto Falloff is switched on.
obj, settings, names = fixture("PreviewOrder", count=2)
obj.data.bones[names[0]].name = "Z_Root"
obj.data.bones[names[1]].name = "A_Child"
select(obj, ["A_Child", "Z_Root"])
rf.load_selected(bpy.context)
assert [i.name for i in settings.affected] == ["A_Child", "Z_Root"]
settings.auto_falloff = True
rf.apply_falloff(bpy.context)
assert [i.name for i in settings.affected] == ["Z_Root", "A_Child"]
assert bases(settings) == [0.2, 0.8]

# Source constraint and transform-driver dependencies must not close a loop.
obj, settings, names = fixture("ConstraintCycle")
c = obj.pose.bones["Source"].constraints.new("COPY_ROTATION")
c.target, c.subtarget = obj, names[-1]
reject(rf.load_selected, obj, "cycle")
obj.pose.bones["Source"].constraints.remove(c)
curve = obj.pose.bones["Source"].driver_add("rotation_euler", 2)
curve.driver.type = "SCRIPTED"
variable = curve.driver.variables.new()
variable.name, variable.type = "angle", "SINGLE_PROP"
variable.targets[0].id = obj
variable.targets[0].data_path = obj.pose.bones[names[-1]].path_from_id("rotation_euler") + "[2]"
curve.driver.expression = "angle"
reject(rf.load_selected, obj, "cycle")

# Orphan source, duplicate suffix cleanup, name collision and altered controller.
obj, settings, names = fixture("Orphan", count=1)
with edit_active_armature(bpy.context, obj) as bones:
    bones[names[0]].use_connect = False
    bones[names[0]].parent = None
obj.data.bones[names[0]].name = "Finger_03.001.R"
names = ["Finger_03.001.R"]
select(obj, names)
settings.mode = "MCH"
rf.load_selected(bpy.context)
with edit_active_armature(bpy.context, obj) as bones:
    b = bones.new("MCH_ROT_Finger_03.R")
    b.head, b.tail = (3, 0, 0), (3, 1, 0)
reject(rf.create_mch, obj, "already exists")
with edit_active_armature(bpy.context, obj) as bones:
    bones.remove(bones["MCH_ROT_Finger_03.R"])
rf.create_mch(bpy.context)
assert obj.data.bones["MCH_ROT_Finger_03.R"].parent is None
obj.data.bones["MCH_ROT_Finger_03.R"].name = "Renamed Mechanism"
rf.connect_rotation(bpy.context)
assert constraint(obj, names[0]).path_from_id().startswith('pose.bones["Renamed Mechanism"]')
with edit_active_armature(bpy.context, obj) as bones:
    bones[names[0]].tail.x += 0.1
reject(rf.connect_rotation, obj, "rest geometry changed")

# Do not adopt a user-deleted/replaced or renamed constraint or driver.
obj, settings, names = fixture("Ownership", count=1)
rf.load_selected(bpy.context)
rf.connect_rotation(bpy.context)
c = constraint(obj, names[0])
old_name = c.name
c.name = "User changed label"
reject(rf.connect_rotation, obj, "renamed")
c.name = old_name
obj.pose.bones[names[0]].constraints.remove(c)
c = obj.pose.bones[names[0]].constraints.new("COPY_ROTATION")
c.name = old_name
reject(rf.connect_rotation, obj, "replaced")
obj.pose.bones[names[0]].constraints.remove(c)

# MCH structure construction and connection from Edit Mode with another rig in
# multi-object Edit Mode: restore both selections; only the active rig changes.
main, settings, names = fixture("EditActive", count=2)
other, _, other_names = fixture("EditOther", count=1)
bpy.ops.object.mode_set(mode="OBJECT")
main.select_set(True)
other.select_set(True)
bpy.context.view_layer.objects.active = main
other_before = structure(other)
bpy.ops.object.mode_set(mode="EDIT")
select(main, names)
select(other, other_names)
before_selected = {b.name: (b.select, b.select_head, b.select_tail) for b in main.data.edit_bones}
settings.mode = "MCH"
rf.load_selected(bpy.context)
rf.create_mch(bpy.context)
assert main.mode == other.mode == "EDIT"
assert {b.name: (b.select, b.select_head, b.select_tail) for b in main.data.edit_bones if b.name in before_selected} == before_selected
rf.connect_rotation(bpy.context)
assert main.mode == other.mode == "EDIT"
bpy.ops.object.mode_set(mode="OBJECT")
assert structure(other) == other_before
assert len(main.data.bones) == 7 and len(settings.affected) == 2
bpy.context.view_layer.objects.active = main
bpy.ops.object.mode_set(mode="POSE")
CASES.append("Topological preview order, orphan/right-side MCH, conflicts/renames, original-rest validation and multi-object Edit Mode scope/restoration")

# New-property and new-constraint failures remove partial data, including IDs.
obj, settings, names = fixture("NewPropertyRollback", count=2)
rf.load_selected(bpy.context)
rf.connect_rotation(bpy.context)
old_write = rf.write_driver
calls = 0
rf.write_driver = fail_driver
reject(rf.connect_property, obj, "Injected")
rf.write_driver = old_write
assert settings.new_property not in obj.pose.bones["Properties"]
assert not obj.animation_data or not obj.animation_data.drivers
obj, settings, names = fixture("NewConstraintRollback", count=2)
rf.load_selected(bpy.context)
old_new = rig.RigTransaction.new_constraint
calls = 0
def fail_constraint(self, pose):
    global calls
    calls += 1
    result = old_new(self, pose)
    if calls == 2:
        raise RuntimeError("Injected new-constraint failure")
    return result
rig.RigTransaction.new_constraint = fail_constraint
reject(rf.connect_rotation, obj, "Injected")
rig.RigTransaction.new_constraint = old_new
assert not any(p.constraints for p in obj.pose.bones)
CASES.append("Rollback after partial new constraints and newly created total property; user replacements are not adopted")

# A linked armature datablock is rejected, even when the object is local.
with tempfile.TemporaryDirectory(prefix="follow_library_", dir=ROOT / "tests") as directory:
    path = str(Path(directory) / "linked.blend")
    bpy.data.libraries.write(path, {obj.data})
    with bpy.data.libraries.load(path, link=True) as (library, imported):
        imported.armatures = [obj.data.name]
    bpy.ops.object.mode_set(mode="OBJECT")
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    linked = bpy.data.objects.new("LocalObjectLinkedData", imported.armatures[0])
    bpy.context.scene.collection.objects.link(linked)
    bpy.context.view_layer.objects.active = linked
    linked.select_set(True)
    bpy.ops.object.mode_set(mode="POSE")
    assert not bpy.ops.ozo.follow_connect_rotation.poll()
    try:
        rf.connect_rotation(bpy.context)
    except ValueError as error:
        assert "local editable" in str(error)
    else:
        raise AssertionError("Linked data must be rejected")
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    linked.select_set(False)
    bpy.ops.object.mode_set(mode="POSE")
CASES.append("Shared and linked/read-only armature rejection and singular-transform rejection")

# Native mix modes are exposed from this Blender build and explicit updates
# keep other constraint settings/structure under the ownership checks.
obj, settings, names = fixture("MixOptions", count=1)
rf.load_selected(bpy.context)
rf.connect_rotation(bpy.context)
source = obj.pose.bones["Source"]
source.rotation_mode = "XYZ"
source.rotation_euler.z = 0.4
pose = obj.pose.bones[names[0]]
pose.rotation_mode = "XYZ"
pose.rotation_euler.z = 0.25
settings.mix_mode = "ADD"
rf.connect_rotation(bpy.context)
evaluate(obj)
assert abs(pose.matrix.to_euler().z - 0.65) < 1e-5
for mix, _, _ in rf.MIX_MODES:
    settings.mix_mode = mix
    rf.connect_rotation(bpy.context)
    assert constraint(obj, names[0]).mix_mode == mix
settings.mix_mode = "REPLACE"
settings.use_x = False
settings.invert_z = True
settings.owner_space = "POSE"
settings.target_space = "POSE"
rf.connect_rotation(bpy.context)
assert not constraint(obj, names[0]).use_x and constraint(obj, names[0]).invert_z
assert constraint(obj, names[0]).owner_space == constraint(obj, names[0]).target_space == "POSE"
assert "CUSTOM" not in {i[0] for i in rf.TARGET_SPACES + rf.OWNER_SPACES}
CASES.append("Native mix options and evaluated Add, axis/invert/space updates, unsupported Custom space excluded")

# Actual Blender Undo/Redo for MCH construction and property-driver connection.
obj, settings, names = fixture("Undo", count=1)
settings.mode = "MCH"
rf.load_selected(bpy.context)
label = obj.name
bpy.context.preferences.edit.use_global_undo = True
bpy.ops.ed.undo_push(message="Before Rotation Follow MCH")
assert bpy.ops.ozo.follow_create_mch() == {"FINISHED"}
bpy.ops.ed.undo_push(message="After Rotation Follow MCH")
bpy.ops.ed.undo()
obj = bpy.data.objects[label]
assert "MCH_ROT_" + names[0] not in obj.data.bones
assert obj.data.bones[names[0]].parent.name == "ROOT" and obj.data.bones[names[0]].use_connect
bpy.ops.ed.redo()
obj = bpy.data.objects[label]
assert obj.data.bones[names[0]].parent.name == "MCH_ROT_" + names[0]
assert bpy.ops.ozo.follow_connect_rotation() == {"FINISHED"}
bpy.ops.ed.undo_push(message="Before Rotation Follow Property")
assert bpy.ops.ozo.follow_connect_property() == {"FINISHED"}
bpy.ops.ed.undo_push(message="After Rotation Follow Property")
bpy.ops.ed.undo()
obj = bpy.data.objects[label]
assert not obj.animation_data or not obj.animation_data.drivers
assert "Rotation_Follow" not in obj.pose.bones["Properties"]
bpy.ops.ed.redo()
obj = bpy.data.objects[label]
assert len(obj.animation_data.drivers) == 1 and obj.pose.bones["Properties"]["Rotation_Follow"] == 1
CASES.append("Actual Blender Undo/Redo restores/reapplies MCH hierarchy, persistent records, custom property and driver")

assert bpy.types.Panel.bl_rna_get_subclass_py("OZO_PT_rotation_follow").bl_parent_id == "OZO_PT_bone_controls"
OZO_Tools.unregister()
assert not hasattr(bpy.types.Armature, "ozo_rotation_follow")
OZO_Tools.register()
assert len(obj.data.ozo_rotation_follow.affected) == 1
OZO_Tools.unregister()
output = {"blender": bpy.app.version_string, "status": "PASS", "cases": CASES}
(ROOT / "outputs" / "rotation_follow_test_report.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
print("OZO_ROTATION_FOLLOW_PASS", json.dumps(output, ensure_ascii=False))
