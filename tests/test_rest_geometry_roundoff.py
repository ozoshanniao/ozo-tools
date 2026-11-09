"""Preserve real rest-edit detection while accepting imported-frame normalization noise."""
from pathlib import Path
from types import SimpleNamespace
import sys

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import OZO_Tools
from OZO_Tools import rig_common as rig, rotation_follow as rf
from OZO_Tools.bone_parenting import edit_active_armature

# Exact matrices from the read-only reported comparison (no character file loaded).
SAVED = {"length": 0.07039431482553482, "matrix": [
    [-9.642019449529471e-08, 2.9802322387695312e-08, 0.9999934434890747, 0.0],
    [-0.9930317401885986, -0.11784699559211731, -1.8347054719924927e-07, -0.15902596712112427],
    [0.1178470179438591, -0.9930316805839539, -7.301568984985352e-07, 0.9881080985069275],
    [0.0, 0.0, 0.0, 1.0]]}
CURRENT = [
    [-8.287207720059087e-08, 3.212740296021366e-08, 1.0000059604644775, -4.6501837103196664e-11],
    [-0.9930317997932434, -0.1178470253944397, 4.41247749449758e-09, -0.15902596712112427],
    [0.1178470328450203, -0.9930318593978882, 7.308693739105365e-07, 0.9881080985069275],
    [0.0, 0.0, 0.0, 1.0]]


def example():
    return SimpleNamespace(matrix_local=Matrix(CURRENT), length=0.07039430737495422,
                           head_local=Vector((0, -0.15902595221996307, 0.9881080985069275)))


raw_error = max(abs(CURRENT[i][j] - SAVED["matrix"][i][j]) for i in range(4) for j in range(4))
assert raw_error > rig.EPSILON
assert rig.same_geometry(example(), SAVED)

bone = example()
bone.head_local.x += rig.EPSILON * 2
assert not rig.same_geometry(bone, SAVED)
bone = example()
bone.length += rig.EPSILON * 2
assert not rig.same_geometry(bone, SAVED)
bone = example()
rotation = Matrix.Rotation(0.0001, 3, "Y") @ bone.matrix_local.to_3x3()
for i in range(3):
    for j in range(3):
        bone.matrix_local[i][j] = rotation[i][j]
assert not rig.same_geometry(bone, SAVED)

for kind in ("scale", "shear", "mirror", "degenerate", "nan", "nonaffine"):
    bone = example()
    if kind == "scale":
        for i in range(3):
            bone.matrix_local[i][2] *= 1.001
    elif kind == "shear":
        bone.matrix_local[0][1] += 0.01
    elif kind == "mirror":
        for i in range(3):
            bone.matrix_local[i][0] *= -1
    elif kind == "degenerate":
        for i in range(3):
            bone.matrix_local[i][0] = 0
    elif kind == "nan":
        bone.matrix_local[0][0] = float("nan")
    else:
        bone.matrix_local[3][0] = 0.1
    assert not rig.same_geometry(bone, SAVED), kind

OZO_Tools.register()
obj = bpy.data.objects.new("RoundoffSynthetic", bpy.data.armatures.new("RoundoffSynthetic"))
bpy.context.scene.collection.objects.link(obj)
for selected in bpy.context.selected_objects:
    selected.select_set(False)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
collection = obj.data.collections.new("Working")
obj.data.collections.active = collection
with edit_active_armature(bpy.context, obj) as bones:
    source = bones.new("Source")
    source.head, source.tail = (-1, 0, 0), (-1, 1, 0)
    controlled = bones.new("Controller")
    controlled.head, controlled.tail = (0, 0, 0), (0, 1, 0)
    controlled.roll = 0.34
    collection.assign(controlled)
bpy.ops.object.mode_set(mode="POSE")
for pose in obj.pose.bones:
    pose.select = pose.name == "Controller"
obj.data.bones.active = obj.data.bones["Controller"]
settings = obj.data.ozo_rotation_follow
settings.rotation_source, settings.mode = "Source", "MCH"
rf.load_selected(bpy.context)
rf.create_mch(bpy.context)
records = rf.read_records(obj.data)
record = records["bindings"][obj.data.bones["Controller"][rig.BONE_ID]]
# Seed a near-unit imported rest-basis discrepancy that the raw-cell check rejects.
for i in range(3):
    record["geometry"]["matrix"][i][2] *= 1.0 - 2e-5
rf.save_records(obj.data, records)
before = rig.rest_geometry(obj.data.bones["Controller"])
rf.connect_rotation(bpy.context)
assert rig.same_geometry(obj.data.bones["Controller"], before)
settings.mch_length = 0.15
rf.update_mch_length(bpy.context)
assert rig.same_geometry(obj.data.bones["Controller"], before)
with edit_active_armature(bpy.context, obj) as bones:
    bones.remove(bones["MCH_ROT_Controller"])
rf.recreate_missing_mch(bpy.context)
rf.connect_rotation(bpy.context)
assert rig.same_geometry(obj.data.bones["Controller"], before)

# Genuine controller edits still stop all writes under the same narrow thresholds.
with edit_active_armature(bpy.context, obj) as bones:
    bones["Controller"].length += 0.001
raw = obj.data[rf.RECORD_KEY]
try:
    rf.connect_rotation(bpy.context)
except ValueError as error:
    assert "rest geometry changed" in str(error)
else:
    raise AssertionError("Real controller length edits must still be rejected")
assert obj.data[rf.RECORD_KEY] == raw
OZO_Tools.unregister()
print("OZO_REST_GEOMETRY_ROUNDOFF_PASS: exact reported matrices, real position/length/rotation edits, corrupt frames, native MCH connect/resize/recovery, source preservation")
