"""Round-trip real hierarchy templates, rest geometry, and saved blend data."""

import json
from pathlib import Path
import sys
import tempfile

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import OZO_Tools
from OZO_Tools.bone_parenting import (
    TEMPLATE_KEY, read_template, restore_original, save_template, to_root,
)


def create_rig(name):
    obj = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    specifications = (
        ("ROOT_SEC", None, (0, 0, 0), (0, 0, 1), False),
        ("ROOT_ALT", None, (3, 0, 0), (3, 0, 1), False),
        ("ORG-shoulder", "ROOT_SEC", (0, 0, 1), (0, 0, 2), True),
        ("DEF-shoulder", "ORG-shoulder", (0, 0, 2), (1, 0, 2), True),
        ("DEF-arm", "DEF-shoulder", (1, 0, 2), (2, 0, 2), True),
        ("DEF-hand", "DEF-arm", (2, 0, 2), (3, 0, 2), True),
        ("DEF-orphan", None, (-1, 0, 0), (-1, 0, 1), False),
        ("def-lower", "DEF-hand", (3, 0, 2), (4, 0, 2), True),
        ("CTRL-child", "DEF-hand", (3, 0, 2), (3, 0, 3), True),
    )
    for index, (name, parent, head, tail, connected) in enumerate(specifications):
        bone = obj.data.edit_bones.new(name)
        bone.head, bone.tail, bone.roll = head, tail, index * 0.13
        bone.parent = obj.data.edit_bones.get(parent) if parent else None
        bone.use_connect = connected
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def snapshot(obj):
    return {
        bone.name: (bone.parent.name if bone.parent else None, bone.use_connect,
                    bone.head_local.copy(), bone.tail_local.copy(), bone.matrix_local.copy())
        for bone in obj.data.bones
    }


def assert_snapshot(obj, expected, hierarchy=True):
    actual = snapshot(obj)
    assert set(actual) == set(expected)
    for name, record in actual.items():
        old = expected[name]
        if hierarchy:
            assert record[:2] == old[:2], (name, record[:2], old[:2])
        assert (record[2] - old[2]).length < 1e-5, name
        assert (record[3] - old[3]).length < 1e-5, name
        assert max(abs(record[4][i][j] - old[4][i][j])
                   for i in range(4) for j in range(4)) < 1e-5, name


def expect_error(action, obj):
    before = snapshot(obj)
    raw = obj.data.get(TEMPLATE_KEY)
    try:
        action()
    except ValueError:
        pass
    else:
        raise AssertionError("Expected validation error")
    assert_snapshot(obj, before)
    assert obj.data.get(TEMPLATE_KEY) == raw


main = create_rig("Main")
other = create_rig("Other")
bpy.context.view_layer.objects.active = main
main.select_set(True)
other.select_set(True)
OZO_Tools.register()
original = snapshot(main)
other_original = snapshot(other)

# Switching never creates a template; explicitly save first.
expect_error(lambda: to_root(bpy.context, "ROOT_SEC"), main)
assert TEMPLATE_KEY not in main.data
assert bpy.ops.ozo.save_parenting_template() == {"FINISHED"}
saved = main.data[TEMPLATE_KEY]
assert len(read_template(main.data)) == 4
assert json.loads(saved)["version"] == 1
assert "UNDO" in bpy.types.Operator.bl_rna_get_subclass_py("OZO_OT_def_to_root").bl_options

for root in ("ROOT_SEC", "ROOT_ALT", "ROOT_SEC"):
    main.data.ozo_bone_parenting.root_bone = root
    assert bpy.ops.ozo.def_to_root() == {"FINISHED"}
    assert main.mode == "OBJECT"
    assert main.select_get() and other.select_get()
    assert bpy.context.active_object == main
    for bone in main.data.bones:
        if bone.name.startswith("DEF"):
            assert bone.parent.name == root
            assert not bone.use_connect
        else:
            assert (bone.parent.name if bone.parent else None, bone.use_connect) == original[bone.name][:2]
    assert_snapshot(main, original, hierarchy=False)
    assert_snapshot(other, other_original)
    assert main.data[TEMPLATE_KEY] == saved
    assert to_root(bpy.context, root) == 0
    assert bpy.ops.ozo.restore_parenting() == {"FINISHED"}
    assert_snapshot(main, original)
    assert restore_original(bpy.context) == 0

expect_error(lambda: to_root(bpy.context, "missing"), main)
expect_error(lambda: to_root(bpy.context, "DEF-hand"), main)
expect_error(lambda: to_root(bpy.context, "CTRL-child"), main)  # Indirect cycle.

# Pose transforms are left alone; this feature changes rest hierarchy only.
bpy.ops.object.mode_set(mode="POSE")
main.pose.bones["DEF-arm"].location.x = 0.25
bpy.context.view_layer.update()
location = main.pose.bones["DEF-arm"].location.copy()
assert to_root(bpy.context, "ROOT_ALT") == 4
assert main.mode == "POSE"
assert main.pose.bones["DEF-arm"].location == location
assert_snapshot(main, original, hierarchy=False)
restore_original(bpy.context)
assert main.mode == "POSE"
assert_snapshot(main, original)
bpy.ops.object.mode_set(mode="EDIT")
assert not bpy.ops.ozo.save_parenting_template.poll()
assert not bpy.ops.ozo.def_to_root.poll()
bpy.ops.object.mode_set(mode="OBJECT")

# Missing/renamed bones invalidate the entire operation before edits.
main.data.bones["DEF-hand"].name = "DEF-hand-renamed"
expect_error(lambda: restore_original(bpy.context), main)
expect_error(lambda: to_root(bpy.context, "ROOT_SEC"), main)
main.data.bones["DEF-hand-renamed"].name = "DEF-hand"
main.data.bones["ORG-shoulder"].name = "ORG-renamed"
expect_error(lambda: restore_original(bpy.context), main)
main.data.bones["ORG-renamed"].name = "ORG-shoulder"

# A connected restore must not silently snap geometry edited in root mode.
to_root(bpy.context, "ROOT_SEC")
bpy.ops.object.mode_set(mode="EDIT")
edit_bone = main.data.edit_bones["DEF-hand"]
old_head = edit_bone.head.copy()
edit_bone.head.z += 0.1
bpy.ops.object.mode_set(mode="OBJECT")
expect_error(lambda: restore_original(bpy.context), main)
bpy.ops.object.mode_set(mode="EDIT")
main.data.edit_bones["DEF-hand"].head = old_head
bpy.ops.object.mode_set(mode="OBJECT")
restore_original(bpy.context)
assert_snapshot(main, original)

main.data[TEMPLATE_KEY] = "not JSON"
expect_error(lambda: to_root(bpy.context, "ROOT_SEC"), main)
main.data[TEMPLATE_KEY] = saved

# Explicit save replaces the baseline; switching/restoring never does.
to_root(bpy.context, "ROOT_ALT")
assert save_template(main.data) == 4
assert main.data[TEMPLATE_KEY] != saved
assert all(parent == "ROOT_ALT" for parent, _ in read_template(main.data).values())
to_root(bpy.context, "ROOT_SEC")
restore_original(bpy.context)
assert all(main.data.bones[name].parent.name == "ROOT_ALT" for name in read_template(main.data))
main.data[TEMPLATE_KEY] = saved
restore_original(bpy.context)
assert_snapshot(main, original)

# Templates and selected roots survive addon unregister/register and blend reload.
main.data.ozo_bone_parenting.root_bone = "ROOT_ALT"
OZO_Tools.unregister()
assert main.data[TEMPLATE_KEY] == saved
assert not hasattr(bpy.types.Armature, "ozo_bone_parenting")
OZO_Tools.register()
assert main.data.ozo_bone_parenting.root_bone == "ROOT_ALT"
to_root(bpy.context, "ROOT_ALT")
with tempfile.TemporaryDirectory(prefix="parenting_test_", dir=ROOT / "tests") as directory:
    path = str(Path(directory) / "roundtrip.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    main = bpy.data.objects["Main"]
    bpy.context.view_layer.objects.active = main
    assert main.data[TEMPLATE_KEY] == saved
    assert main.data.ozo_bone_parenting.root_bone == "ROOT_ALT"
    restore_original(bpy.context)
    assert_snapshot(main, original)
OZO_Tools.unregister()
print("OZO_PARENTING_PASS: manual templates, configurable roots, geometry, cycles, selection/mode, persistence")
