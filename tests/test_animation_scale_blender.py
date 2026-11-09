"""Synthetic coverage of normalization, unsupported inputs, rollback, and Undo."""

from pathlib import Path
import json
import math
import sys

import bpy
import numpy as np
from mathutils import Matrix

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import OZO_Tools
from OZO_Tools import animation_scale as tool


def fixture(factor=0.01, animated_scale=True, mesh_count=2):
    units = 0.01 if factor > 1 else 1.0
    bpy.context.scene.render.frame_map_old = bpy.context.scene.render.frame_map_new = 100
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    armature = bpy.data.armatures.new("ScaleTest")
    src = bpy.data.objects.new("ScaleTest", armature)
    bpy.context.scene.collection.objects.link(src)
    bpy.context.view_layer.objects.active = src
    src.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for name, head, tail, parent in (
        ("Root", (0, 0, 0), (0, 0, 100), None),
        ("Child", (0, 0, 100), (25, 0, 180), "Root"),
        ("Unkeyed", (70, 0, 0), (90, 0, 40), "Root"),
    ):
        bone = armature.edit_bones.new(name)
        bone.head, bone.tail = tuple(v * units for v in head), tuple(v * units for v in tail)
        bone.parent = armature.edit_bones.get(parent) if parent else None
    bpy.ops.object.mode_set(mode="OBJECT")
    src.scale = (factor,) * 3
    src.rotation_euler = (0.15, 0.2, -0.1)
    static = src.pose.bones["Unkeyed"]
    static.rotation_mode = "AXIS_ANGLE"
    static.rotation_axis_angle = (0.3, 0, 1, 0)
    static.location = (11 * units, -3 * units, 2 * units)
    static.scale = (1.1, 0.9, 1.05)
    root, child = src.pose.bones["Root"], src.pose.bones["Child"]
    child.rotation_mode = "XYZ"
    for frame in (1.0, 4.25, 8.0):
        root.location = (10 * math.sin(frame) * units, frame * units, 2 * units)
        root.keyframe_insert("location", frame=frame)
        child.rotation_euler = (0.03 * frame, 0.02 * frame, 0.01 * frame)
        child.keyframe_insert("rotation_euler", frame=frame)
        child.scale = (1 + 0.01 * frame, 1, 1 - 0.005 * frame)
        child.keyframe_insert("scale", frame=frame)
        src.location = (3 + 0.1 * frame, 2, 0.3)
        src.keyframe_insert("location", frame=frame)
        if animated_scale:
            src.keyframe_insert("scale", frame=frame)
    curves = tool.action_curves(src.animation_data.action, src.animation_data.action_slot)
    for curve in curves:
        if curve.data_path == 'pose.bones["Root"].location':
            for key in curve.keyframe_points:
                key.handle_left_type = key.handle_right_type = "FREE"
                key.handle_left = (key.co.x - 0.7, key.co.y - 1.4 * units)
                key.handle_right = (key.co.x + 0.7, key.co.y + 2.1 * units)
            curve.update()
    meshes = []
    for index in range(mesh_count):
        data = bpy.data.meshes.new("ScaleMesh")
        data.from_pydata([tuple(v * units for v in point) for point in ((0, 0, 0), (20, 0, 110), (0, 20, 180))], [], [(0, 1, 2)])
        mesh = bpy.data.objects.new("ScaleMesh", data)
        bpy.context.scene.collection.objects.link(mesh)
        mesh.parent = src
        mod = mesh.modifiers.new("Skin", "ARMATURE")
        mod.object = src
        mod.use_deform_preserve_volume = bool(index % 2)
        mesh.vertex_groups.new(name="Root").add([0], 1.0, "REPLACE")
        mesh.vertex_groups.new(name="Child").add([1, 2], 1.0, "REPLACE")
        meshes.append(mesh)
    bpy.context.scene.frame_set(3, subframe=0.25)
    bpy.context.view_layer.update()
    return src, meshes


def signature(action):
    return [
        (curve.data_path, curve.array_index,
         [(tuple(k.co), tuple(k.handle_left), tuple(k.handle_right), k.interpolation,
           k.handle_left_type, k.handle_right_type) for k in curve.keyframe_points])
        for curve in tool.action_curves(action, action.slots[0])
    ]


def state(src, meshes):
    return (
        src.data, tuple(mesh.data for mesh in meshes), src.animation_data.action,
        signature(src.animation_data.action), src.animation_data.action.use_fake_user,
        tuple(src.scale), tool.pose_channels(src), bpy.context.scene.frame_current,
        bpy.context.scene.frame_subframe, src.mode, bpy.context.active_object,
        set(bpy.context.selected_objects), len(bpy.data.armatures), len(bpy.data.meshes), len(bpy.data.actions),
        tuple((tuple(tuple(row) for row in mesh.matrix_parent_inverse),
               tuple((prop, tuple(getattr(mesh, prop))) for prop in tool.TRANSFORMS)) for mesh in meshes),
    )


OZO_Tools.register()
successes = []
for factor, animated, mesh_count, pose in ((0.01, True, 2, True), (2.5, False, 1, False), (0.2, True, 0, False)):
    print("SCALE_TEST_CASE", factor, animated, mesh_count, pose, flush=True)
    src, meshes = fixture(factor, animated, mesh_count)
    if pose:
        bpy.ops.object.mode_set(mode="POSE")
    before = state(src, meshes)
    frames = [1 + step * 0.25 for step in range(29)]
    baseline = []
    for f in frames:
        tool.set_sample(bpy.context.scene, f)
        baseline.append(tool.capture_world(bpy.context, src, meshes))
    bpy.context.scene.frame_set(before[7], subframe=before[8])
    original_action = src.animation_data.action
    result = tool.normalize_scale(bpy.context)
    assert not result.skipped and result.meshes == mesh_count
    assert bpy.context.active_object == before[10] and src.mode == before[9]
    assert set(bpy.context.selected_objects) == before[11]
    assert (bpy.context.scene.frame_current, bpy.context.scene.frame_subframe) == before[7:9]
    assert signature(original_action) == before[3]
    assert original_action.use_fake_user
    assert tuple(src.pose.bones["Unkeyed"].location) == tuple(v * float(factor) for v in before[6]["Unkeyed"]["location"]) or all(
        abs(src.pose.bones["Unkeyed"].location[i] - before[6]["Unkeyed"]["location"][i] * factor) < 1e-5 for i in range(3))
    for f, (old_bones, old_meshes) in zip(frames, baseline):
        tool.set_sample(bpy.context.scene, f)
        new_bones, new_meshes = tool.capture_world(bpy.context, src, meshes)
        assert tool.max_distance(old_bones, new_bones) < 2e-5
        assert all(tool.max_distance(a, b) < 2e-5 for a, b in zip(old_meshes, new_meshes))
        assert tuple(src.scale) == (1, 1, 1)
    normalized = state(src, meshes)
    assert tool.normalize_scale(bpy.context).skipped
    assert state(src, meshes) == normalized
    # Reassigning an unconverted backup Action must never bake the rig twice.
    normalized_action = src.animation_data.action
    src.animation_data.action = original_action
    src.animation_data.action_slot = original_action.slots[0]
    bpy.context.scene.frame_set(bpy.context.scene.frame_current, subframe=bpy.context.scene.frame_subframe)
    assert any("same normalization" in issue for issue in tool.inspect_rig(bpy.context).issues)
    before_wrong_action = state(src, meshes)
    try:
        tool.normalize_scale(bpy.context)
    except ValueError:
        pass
    else:
        raise AssertionError("Mismatched source Action must be rejected")
    assert state(src, meshes) == before_wrong_action
    src.animation_data.action = normalized_action
    src.animation_data.action_slot = normalized_action.slots[0]
    src.scale = (1, 1, 1)
    bpy.context.scene.frame_set(bpy.context.scene.frame_current, subframe=bpy.context.scene.frame_subframe)
    successes.append((factor, animated, mesh_count, pose))

# Reproduce the user's imported parent-inverse matrix without clearing it.
roundoff_matrix = Matrix((
    (1.0, -3.725290298461914e-09, 3.725289943190546e-08, 1.1920927818209748e-06),
    (-3.725290298461914e-09, 1.0, -1.4901161193847656e-08, 1.1622905731201172e-06),
    (3.725289943190546e-08, -1.4901161193847656e-08, 0.9999998807907104, 0.0),
    (0, 0, 0, 1),
))
roundoff_results = []
for factor in (0.01, 2.5):
    src, meshes = fixture(factor=factor)
    for mesh in meshes:
        mesh.matrix_parent_inverse = roundoff_matrix
    meshes[1].location = (2e-6, -1e-6, 0)
    meshes[1].rotation_euler = (1e-6, 0, 0)
    meshes[1].scale = (1, 1 + 1e-6, 1)
    bpy.context.view_layer.update()
    assert tool.inspect_rig(bpy.context).ready
    plan = tool.inspect_rig(bpy.context)
    frames = plan.samples
    baseline = []
    for frame in frames:
        tool.set_sample(bpy.context.scene, frame)
        baseline.append(tool.capture_world(bpy.context, src, meshes))
    result = tool.normalize_scale(bpy.context)
    for mesh in meshes:
        for i in range(3):
            assert abs(mesh.matrix_parent_inverse[i][3] - roundoff_matrix[i][3] * factor) < 1e-10
            assert tuple(mesh.matrix_parent_inverse[i][:3]) == tuple(roundoff_matrix[i][:3])
    max_error = 0.0
    for frame, (old_bones, old_vertices) in zip(frames, baseline):
        tool.set_sample(bpy.context.scene, frame)
        now_bones, now_vertices = tool.capture_world(bpy.context, src, meshes)
        max_error = max(max_error, tool.max_distance(old_bones, now_bones),
                        *(tool.max_distance(a, b) for a, b in zip(old_vertices, now_vertices)))
    assert max_error < tool.WORLD_TOLERANCE
    roundoff_results.append({"factor": factor, "max_world_error": max_error})


def reject(label, change):
    src, meshes = fixture()
    change(src, meshes)
    bpy.context.view_layer.update()
    before = state(src, meshes)
    issues = tool.inspect_rig(bpy.context).issues
    assert issues, label
    try:
        tool.normalize_scale(bpy.context)
    except ValueError:
        pass
    else:
        raise AssertionError(label)
    assert state(src, meshes) == before, label
    return label


def change_scale_key(src, meshes):
    curve = next(c for c in tool.action_curves(src.animation_data.action, src.animation_data.action_slot) if c.data_path == "scale")
    curve.keyframe_points[-1].co.y = 0.02


def change_scale_handle(src, meshes):
    curve = next(c for c in tool.action_curves(src.animation_data.action, src.animation_data.action_slot) if c.data_path == "scale")
    key = curve.keyframe_points[1]
    key.handle_left_type = "FREE"
    key.handle_left.y = 0.02


def external_constraint(src, meshes):
    other = bpy.data.objects.new("External", None)
    bpy.context.scene.collection.objects.link(other)
    other.constraints.new("COPY_TRANSFORMS").target = src


def external_material_driver(src, meshes):
    material = bpy.data.materials.new("ExternalDriver")
    meshes[0].data.materials.append(material)
    curve = material.driver_add("diffuse_color", 0)
    variable = curve.driver.variables.new()
    variable.type = "SINGLE_PROP"
    variable.targets[0].id = src
    variable.targets[0].data_path = "scale[0]"
    curve.driver.expression = variable.name


cases = [
    ("nonuniform", lambda s, m: setattr(s, "scale", (0.01, 0.02, 0.01))),
    ("negative", lambda s, m: setattr(s, "scale", (-0.01,) * 3)),
    ("zero", lambda s, m: setattr(s, "scale", (0,) * 3)),
    ("dynamic scale key", change_scale_key), ("dynamic scale handle", change_scale_handle),
    ("object constraint", lambda s, m: s.constraints.new("LIMIT_LOCATION")),
    ("bone constraint", lambda s, m: s.pose.bones[0].constraints.new("LIMIT_ROTATION")),
    ("driver", lambda s, m: s.driver_add("scale", 0)),
    ("NLA", lambda s, m: s.animation_data.nla_tracks.new()),
    ("multi-slot", lambda s, m: s.animation_data.action.slots.new(id_type="OBJECT", name="Another")),
    ("additive Action", lambda s, m: setattr(s.animation_data, "action_blend_type", "ADD")),
    ("shape keys", lambda s, m: m[0].shape_key_add(name="Basis")),
    ("shared armature", lambda s, m: bpy.context.scene.collection.objects.link(bpy.data.objects.new("Shared", s.data))),
    ("shared mesh", lambda s, m: bpy.context.scene.collection.objects.link(bpy.data.objects.new("Shared", m[0].data))),
    ("mesh local transform", lambda s, m: setattr(m[0], "location", (1, 0, 0))),
    ("parent inverse", lambda s, m: setattr(m[0], "matrix_parent_inverse", Matrix.Translation((1, 0, 0)))),
    ("parent inverse above roundoff tolerance", lambda s, m: setattr(m[0], "matrix_parent_inverse", Matrix.Translation((0.0001, 0, 0)))),
    ("bone parenting", lambda s, m: setattr(m[0], "parent_type", "BONE")),
    ("extra modifier", lambda s, m: m[0].modifiers.new("Subsurf", "SUBSURF")),
    ("unparented bound mesh", lambda s, m: setattr(m[0], "parent", None)),
    ("external constraint", external_constraint),
    ("external material driver", external_material_driver),
    ("delta transform", lambda s, m: setattr(s, "delta_scale", (2, 2, 2))),
    ("B-Bone", lambda s, m: setattr(s.data.bones[0], "bbone_segments", 2)),
    ("scene time remapping", lambda s, m: setattr(bpy.context.scene.render, "frame_map_new", 200)),
]
rejected = [reject(label, change) for label, change in cases]

# Fake users retain data; they are not an additional geometry-sharing object.
src, meshes = fixture()
src.data.use_fake_user = True
for mesh in meshes:
    mesh.data.use_fake_user = True
assert tool.inspect_rig(bpy.context).ready
tool.normalize_scale(bpy.context)
assert tool.normalize_scale(bpy.context).skipped

# A mismatch after the swap must restore pointers, Action contents, pose channels,
# current frame/mode/selection, fake-user state, and delete all temporary copies.
src, meshes = fixture()
meshes[0].matrix_parent_inverse = roundoff_matrix
meshes[0].location = (1e-6, 0, 0)
bpy.ops.object.mode_set(mode="POSE")
before = state(src, meshes)
plan = tool.inspect_rig(bpy.context)
capture = tool.capture_world
calls = [0]


def mismatched_capture(*args):
    calls[0] += 1
    bones, vertices = capture(*args)
    if calls[0] > len(plan.samples):
        bones[0, 0] += 1.0
    return bones, vertices


tool.capture_world = mismatched_capture
try:
    try:
        tool.normalize_scale(bpy.context)
    except RuntimeError as error:
        assert "verification failed" in str(error)
    else:
        raise AssertionError("Expected mismatch and rollback")
finally:
    tool.capture_world = capture
assert state(src, meshes) == before

# Callback compatibility must never remove or reorder another addon's handlers.
original_pre = tuple(bpy.app.handlers.frame_change_pre)
original_post = tuple(bpy.app.handlers.frame_change_post)
callback_counts = {"unknown": 0, "amp": 0, "arp": 0}


def unknown_frame_callback(*args):
    callback_counts["unknown"] += 1


def amp_frame_callback(*args):
    callback_counts["amp"] += 1


def arp_frame_callback(*args):
    callback_counts["arp"] += 1


amp_frame_callback.__module__ = "bl_ext.user_default.amp_animate_pro.utils.handlers"
amp_frame_callback.__name__ = "amp_on_frame_change_post"
arp_frame_callback.__module__ = "bl_ext.user_default.auto_rig_pro.src.rig_functions"
arp_frame_callback.__name__ = "rig_layers_anim_update"
bpy.app.handlers.frame_change_post.append(unknown_frame_callback)
try:
    src, meshes = fixture(factor=1.0)
    callback_counts["unknown"] = 0
    before = state(src, meshes)
    assert tool.inspect_rig(bpy.context).ready
    assert tool.normalize_scale(bpy.context).skipped
    assert state(src, meshes) == before
    assert callback_counts["unknown"] == 0  # A skip must not trigger callbacks.
    src, meshes = fixture()
    callback_counts["unknown"] = 0
    before = state(src, meshes)
    plan = tool.inspect_rig(bpy.context)
    assert any("unknown_frame_callback" in issue for issue in plan.issues)
    try:
        tool.normalize_scale(bpy.context)
    except ValueError:
        pass
    else:
        raise AssertionError("Unexamined callbacks must block a non-unit conversion")
    assert state(src, meshes) == before
    assert callback_counts["unknown"] == 0
finally:
    bpy.app.handlers.frame_change_post.remove(unknown_frame_callback)

bpy.app.handlers.frame_change_post.extend((amp_frame_callback, arp_frame_callback))
fingerprint = tool.callback_fingerprint
added_scene_property = not hasattr(bpy.types.Scene, "arp_layers_animated")
if added_scene_property:
    bpy.types.Scene.arp_layers_animated = bpy.props.BoolProperty(default=False)
try:
    src, meshes = fixture()
    # Names alone cannot authorize compatibility; changed callback code is blocked.
    assert len(tool.frame_callback_issues(bpy.context)[0]) == 2

    def audited_fingerprint(callback):
        if callback in (amp_frame_callback, arp_frame_callback):
            return next(value for (module, name), value in tool.INACTIVE_CALLBACKS.items()
                        if name == callback.__name__)
        return fingerprint(callback)

    tool.callback_fingerprint = audited_fingerprint
    bpy.context.scene.arp_layers_animated = False
    issues, notes = tool.frame_callback_issues(bpy.context)
    assert not issues and len(notes) == 2
    tool.normalize_scale(bpy.context)
    assert callback_counts["amp"] > 0 and callback_counts["arp"] > 0
    assert tuple(bpy.app.handlers.frame_change_post) == original_post + (amp_frame_callback, arp_frame_callback)
    bpy.context.scene.arp_layers_animated = True
    assert any("rig_layers_anim_update" in issue for issue in tool.frame_callback_issues(bpy.context)[0])
    from types import SimpleNamespace
    fake_context = SimpleNamespace(screen=SimpleNamespace(is_animation_playing=True), scene=bpy.context.scene)
    assert any("amp_on_frame_change_post" in issue for issue in tool.frame_callback_issues(fake_context)[0])
finally:
    tool.callback_fingerprint = fingerprint
    bpy.app.handlers.frame_change_post.remove(amp_frame_callback)
    bpy.app.handlers.frame_change_post.remove(arp_frame_callback)
    if added_scene_property:
        del bpy.types.Scene.arp_layers_animated
assert tuple(bpy.app.handlers.frame_change_pre) == original_pre
assert tuple(bpy.app.handlers.frame_change_post) == original_post

# Exercise actual Blender undo/redo rather than only inspecting bl_options.
src, meshes = fixture(mesh_count=1)
source_name = src.name
action_name = src.animation_data.action.name
before_points = tool.capture_world(bpy.context, src, meshes)
bpy.context.preferences.edit.use_global_undo = True
bpy.ops.ed.undo_push(message="Before Normalize Scale")
assert bpy.ops.ozo.normalize_animation_scale() == {"FINISHED"}
assert tuple(src.scale) == (1, 1, 1)
bpy.ops.ed.undo_push(message="After Normalize Scale")
bpy.ops.ed.undo()
src = bpy.data.objects[source_name]
assert src.animation_data.action.name == action_name
assert all(abs(v - 0.01) < 1e-7 for v in src.scale)
bpy.ops.ed.redo()
src = bpy.data.objects[source_name]
assert tuple(src.scale) == (1, 1, 1)
meshes = [child for child in src.children if child.type == "MESH"]
after_points = tool.capture_world(bpy.context, src, meshes)
assert tool.max_distance(before_points[0], after_points[0]) < 2e-5
assert tool.max_distance(before_points[1][0], after_points[1][0]) < 2e-5

OZO_Tools.unregister()
assert not hasattr(bpy.types.Scene, "ozo_animation_scale")
OZO_Tools.register()
OZO_Tools.unregister()
report = {"status": "PASS", "blender": bpy.app.version_string, "success_cases": successes,
          "rejected_cases": rejected, "rollback": True, "undo_redo": True,
          "callback_compatibility": True, "callback_lists_preserved": True}
report["roundoff_matrices"] = roundoff_results
(ROOT / "tests" / "animation_scale_result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print("OZO_ANIMATION_SCALE_PASS", json.dumps(report))
