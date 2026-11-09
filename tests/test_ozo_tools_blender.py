"""Run with Blender --background --factory-startup --python this_file."""

import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import OZO_Tools
from OZO_Tools.bone_constraints import (
    CONSTRAINT_NAME, EXPECTED_SETTINGS, is_correct, synchronize, validate_prefixes,
)


def rig(name, names, scene=None):
    obj = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    (scene or bpy.context.scene).collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for i, name in enumerate(names):
        bone = obj.data.edit_bones.new(name)
        bone.head = (i * 2, 0, 0)
        bone.tail = (i * 2, 0, 1)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def copy(obj, bone_name, target=None, subtarget="", correct=False):
    constraint = obj.pose.bones[bone_name].constraints.new("COPY_TRANSFORMS")
    constraint.target = target
    constraint.subtarget = subtarget
    if correct:
        for key, value in EXPECTED_SETTINGS.items():
            setattr(constraint, key, value)
    return constraint


def snapshot(scene):
    return [
        (obj.name, bone.name, c.name, c.type,
         c.target.name if c.target else None, c.subtarget,
         tuple(getattr(c, k) for k in EXPECTED_SETTINGS))
        for obj in scene.objects if obj.type == "ARMATURE"
        for bone in obj.pose.bones for c in bone.constraints
        if c.type == "COPY_TRANSFORMS"
    ]


bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
names = [
    "DEF-new", "ORG-new", "DEF-good", "ORG-good",
    "DEF-wrong", "ORG-wrong", "DEF-other", "ORG-other",
    "DEF-dupe", "ORG-dupe", "DEF-missing", "DEF-case", "org-case",
    "def-lower", "ORG-lower", "DEF-Mixed", "ORG-mixed",
    "DEF_underscore", "ORG_underscore", "DEF-conflict", "ORG-conflict",
    "DEF-driven", "ORG-driven", "DEF-keyed", "ORG-keyed",
    "DEF-broken", "ORG-broken", "DEF-preserve", "ORG-preserve",
    "MCH-one", "MCH-two",
]
main = rig("Main", names)
hidden = rig("Hidden", ["DEF-new", "ORG-new"])
hidden.hide_set(True)
hidden.hide_viewport = True
wrong_target = rig("Other", ["ORG-wrong"])
good = copy(main, "DEF-good", main, "ORG-good", correct=True)
good.name = "Keep this name"
good_ptr = good.as_pointer()
wrong = copy(main, "DEF-wrong", wrong_target, "ORG-wrong")
wrong.owner_space = "LOCAL"
wrong.target_space = "POSE"
wrong.mix_mode = "BEFORE_FULL"
wrong.influence = 0.25
wrong.mute = True
wrong.head_tail = 0.5
wrong.use_bbone_shape = True
wrong.remove_target_shear = True
wrong_ptr = wrong.as_pointer()
copy(main, "DEF-other", main, "MCH-one")  # Lone unrelated target is repaired.
dupe_good = copy(main, "DEF-dupe", main, "ORG-dupe", correct=True)
dupe_ptr = dupe_good.as_pointer()
copy(main, "DEF-dupe", main, "ORG-other")
copy(main, "DEF-broken", main, "deleted-bone")
copy(main, "DEF-conflict", main, "MCH-one")
copy(main, "DEF-conflict", main, "MCH-two")
preserve = copy(main, "DEF-preserve", main, "MCH-one", correct=True)
copy(main, "DEF-preserve", main, "ORG-preserve", correct=True)
other_type = main.pose.bones["DEF-new"].constraints.new("LIMIT_ROTATION")
driver = copy(main, "DEF-driven", main, "ORG-driven", correct=True)
driver.driver_add("influence").driver.expression = "0.5"
keyed = copy(main, "DEF-keyed", main, "ORG-keyed", correct=True)
keyed.keyframe_insert("influence", frame=1)

# A datablock outside this scene is never scanned.
outside = rig("Outside", ["DEF-new", "ORG-new"])
bpy.data.scenes.new("OutsideScene").collection.objects.link(outside)
scene.collection.objects.unlink(outside)

OZO_Tools.register()
assert hasattr(scene, "ozo_bone_constraints")
result = synchronize(scene, "DEF", "ORG")
assert result.armatures == 3, result
assert result.added == 3, result
assert result.repaired == 3, result
assert result.correct == 3, result
assert result.duplicates_removed == 1, result
assert result.missing == 3, result
assert result.conflicts == 3, result
assert result.errors == 0, result
assert good.as_pointer() == good_ptr and good.name == "Keep this name"
assert wrong.as_pointer() == wrong_ptr
assert is_correct(wrong, main, "ORG-wrong")
assert main.pose.bones["DEF-dupe"].constraints[0].as_pointer() == dupe_ptr
assert len(main.pose.bones["DEF-dupe"].constraints) == 1
assert preserve.subtarget == "MCH-one"
assert len(main.pose.bones["DEF-preserve"].constraints) == 2
assert other_type in list(main.pose.bones["DEF-new"].constraints)
assert not main.pose.bones["def-lower"].constraints
assert not main.pose.bones["DEF-case"].constraints
assert not main.pose.bones["DEF-Mixed"].constraints
assert not outside.pose.bones["DEF-new"].constraints

# Repeat runs must not change a constraint name, order, target, or setting.
before = snapshot(scene)
again = synchronize(scene, "DEF", "ORG")
assert again.added == again.repaired == again.duplicates_removed == 0, again
assert again.correct == 9, again
assert snapshot(scene) == before

# Apply selected spaces, all seven native mixing modes, and influence.
options = scene.ozo_bone_constraints
options.target_space = "LOCAL"
options.owner_space = "POSE"
options.influence = 0.35
for mix in ("REPLACE", "BEFORE_FULL", "BEFORE", "BEFORE_SPLIT",
            "AFTER_FULL", "AFTER", "AFTER_SPLIT"):
    options.mix_mode = mix
    synchronize(scene, "DEF", "ORG", options)
    check = main.pose.bones["DEF-new"].constraints[-1]
    assert check.target_space == "LOCAL"
    assert check.owner_space == "POSE"
    assert check.mix_mode == mix
    assert abs(check.influence - 0.35) < 1e-6
    repeat_options = synchronize(scene, "DEF", "ORG", options)
    assert repeat_options.added == repeat_options.repaired == 0
options.target_space = "CUSTOM"
try:
    synchronize(scene, "DEF", "ORG", options)
except ValueError:
    pass
else:
    raise AssertionError("Custom space must require an object")
options.space_object = wrong_target
options.space_subtarget = "ORG-wrong"
synchronize(scene, "DEF", "ORG", options)
check = main.pose.bones["DEF-new"].constraints[-1]
assert check.space_object == wrong_target
assert check.space_subtarget == "ORG-wrong"
options.space_subtarget = "missing"
try:
    synchronize(scene, "DEF", "ORG", options)
except ValueError:
    pass
else:
    raise AssertionError("Custom space must validate its bone")
options.target_space = "WORLD"
options.owner_space = "WORLD"
options.mix_mode = "REPLACE"
options.influence = 1.0
synchronize(scene, "DEF", "ORG", options)
assert snapshot(scene) == before  # Returning to defaults clears custom space.

# Native enum options are available; every space can be assigned to constraints.
for prop in ("target_space", "owner_space"):
    items = options.bl_rna.properties[prop].enum_items
    native_items = bpy.types.CopyTransformsConstraint.bl_rna.properties[prop].enum_items
    assert {i.identifier for i in items} == {i.identifier for i in native_items}
    for item in items:
        setattr(options, prop, item.identifier)
        options.space_subtarget = "ORG-wrong"
        synchronize(scene, "DEF", "ORG", options)
        assert getattr(check, prop) == item.identifier
    setattr(options, prop, "WORLD")
synchronize(scene, "DEF", "ORG", options)
assert snapshot(scene) == before

# Check evaluated transforms, not only the stored constraint properties.
main.pose.bones["ORG-new"].matrix_basis = Matrix.Translation((1.0, 2.0, 3.0))
bpy.context.view_layer.update()
evaluated = main.evaluated_get(bpy.context.evaluated_depsgraph_get())
owner_matrix = evaluated.pose.bones["DEF-new"].matrix
target_matrix = evaluated.pose.bones["ORG-new"].matrix
assert max(abs(owner_matrix[i][j] - target_matrix[i][j])
           for i in range(4) for j in range(4)) < 1e-5

for a, b in [("", "ORG"), ("DEF", ""), ("DEF", "DEF"), ("D", "DEF")]:
    try:
        validate_prefixes(a, b)
    except ValueError:
        pass
    else:
        raise AssertionError((a, b))
validate_prefixes("DEF", "def")  # Case-distinct prefixes are valid.

# The public button works without a selected/active rig.
bpy.context.view_layer.objects.active = None
assert bpy.ops.ozo.sync_bone_constraints() == {"FINISHED"}
assert scene.ozo_bone_constraints.last_result
assert snapshot(scene) == before
scene.ozo_bone_constraints.prefix_a = ""
try:
    bpy.ops.ozo.sync_bone_constraints()
except RuntimeError:
    pass  # Blender surfaces an ERROR operator report as RuntimeError.
else:
    raise AssertionError("Empty prefix must fail")
assert snapshot(scene) == before
scene.ozo_bone_constraints.prefix_a = "DEF"
bpy.context.view_layer.objects.active = main
main.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
assert not bpy.ops.ozo.sync_bone_constraints.poll()
bpy.ops.object.mode_set(mode="OBJECT")
OZO_Tools.unregister()
assert not hasattr(bpy.types.Scene, "ozo_bone_constraints")
OZO_Tools.register()
OZO_Tools.unregister()

report = {"blender": bpy.app.version_string, "first_run": vars(result),
          "repeat_run": vars(again), "status": "PASS"}
(ROOT / "tests" / "test_result.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("OZO_TEST_PASS", json.dumps(report, ensure_ascii=False))
