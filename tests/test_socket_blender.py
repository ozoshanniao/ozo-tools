"""Exercise socket rest placement, world axes, ordered constraints and isolation."""
from pathlib import Path
import sys
import tempfile

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import OZO_Tools
from OZO_Tools import bone_socket as socket
from OZO_Tools.bone_parenting import edit_active_armature

OZO_Tools.register()


def fixture(label="Test", root_name="ROOT"):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    obj = bpy.data.objects.new(label, bpy.data.armatures.new(label))
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    collection = obj.data.collections.new("Working")
    obj.data.collections.new("Existing MCH", parent=collection)
    obj.data.collections.active = collection
    with edit_active_armature(bpy.context, obj) as bones:
        for name, head, tail in ((root_name, (0, 0, 0), (0, 1, 0)),
                                 ("Parent", (0, 0, 0), (0, 0, 1)),
                                 ("Controller.L.001", (0, 0, 1), (1, 0, 1))):
            bone = bones.new(name)
            bone.head, bone.tail = head, tail
            collection.assign(bone)
        bones["Controller.L.001"].parent = bones["Parent"]
        bones["Controller.L.001"].use_connect = True
    bpy.ops.object.mode_set(mode="POSE")
    select_source(obj)
    return obj


def select_source(obj):
    if obj.mode == "EDIT":
        for bone in obj.data.edit_bones:
            bone.select = bone.select_head = bone.select_tail = False
        bone = obj.data.edit_bones["Controller.L.001"]
        bone.select_head = True
        obj.data.edit_bones.active = bone
    else:
        for bone in obj.pose.bones:
            bone.select = bone.name == "Controller.L.001"
        obj.data.bones.active = obj.data.bones["Controller.L.001"]


def snapshot(obj):
    return {b.name: (b.parent.name if b.parent else None, b.use_connect,
                    tuple(tuple(row) for row in b.matrix_local), b.length, b.use_deform,
                    tuple((c.type, c.name) for c in obj.pose.bones[b.name].constraints))
            for b in obj.data.bones}


def close(a, b, epsilon=3e-5):
    assert (Vector(a) - Vector(b)).length < epsilon, (tuple(a), tuple(b))


def expect_error(obj, fn=socket.create_socket):
    mode = obj.mode
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="OBJECT")
    before = snapshot(obj)
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")
    try:
        fn(bpy.context)
    except (ValueError, RuntimeError) as error:
        print("Expected rejection:", error)
    else:
        raise AssertionError("Expected failure")
    assert obj.mode == mode
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="OBJECT")
    assert snapshot(obj) == before
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")


obj = fixture()
obj.pose.bones["Controller.L.001"].constraints.new("LIMIT_ROTATION")
obj.pose.bones["Controller.L.001"].keyframe_insert("location", frame=1)
obj.pose.bones["Controller.L.001"].driver_add("scale", 2).driver.expression = "1.0"
source_before = snapshot(obj)["Controller.L.001"]
assert bpy.ops.ozo.create_socket() == {"FINISHED"}
assert obj.mode == "POSE"
assert bpy.context.active_pose_bone.name == "Controller.L.001"
outer = obj.data.bones["MCH_Socket_Controller.L"]
intermediate = obj.data.bones["MCH_INT_Socket_Controller.L"]
assert outer.parent.name == "Parent" and not outer.use_connect
assert intermediate.parent.name == "ROOT" and not intermediate.use_connect
assert obj.data.bones["Controller.L.001"].parent == intermediate
assert not obj.data.bones["Controller.L.001"].use_connect
assert not outer.use_deform and not intermediate.use_deform
assert obj.data.bones["Controller.L.001"].use_deform
assert abs(outer.length - 1) < 1e-6 and abs(intermediate.length - 0.5) < 1e-6
close(outer.head_local, (0, 0, 1))
close(intermediate.head_local, (0, 0, 1))
close(outer.tail_local, (0, 0, 2))
close(outer.matrix_local.to_3x3().col[0], (1, 0, 0))
assert not obj.pose.bones[outer.name].constraints
constraints = obj.pose.bones[intermediate.name].constraints
assert [c.type for c in constraints] == ["COPY_LOCATION", "COPY_SCALE", "COPY_ROTATION"]
assert [c.influence for c in constraints] == [1, 1, 1]
for constraint in constraints:
    assert constraint.target == obj and constraint.subtarget == outer.name
    assert constraint.target_space == constraint.owner_space == "WORLD"
assert len(obj.pose.bones["Controller.L.001"].constraints) == 1
assert len(obj.animation_data.drivers) == 1
assert snapshot(obj)["Controller.L.001"][2] == source_before[2]

# Socket inherits the source's former parent, without moving rest geometry or
# retaining Connected. Parent animation reaches INT through world constraints.
parent = obj.pose.bones["Parent"]
parent.rotation_mode = "XYZ"
parent.rotation_euler.z = 0.4
parent.location = (0.4, 0.2, -0.1)
bpy.context.view_layer.update()
expected = parent.matrix @ parent.bone.matrix_local.inverted() @ outer.matrix_local
actual = obj.pose.bones[outer.name].matrix
assert max(abs(expected[i][j] - actual[i][j]) for i in range(4) for j in range(4)) < 1e-5
close(obj.pose.bones[intermediate.name].head, obj.pose.bones[outer.name].head)
parent.rotation_euler = (0, 0, 0)
parent.location = (0, 0, 0)

# Socket translation/scale follows; Socket rotation is isolated at influence 0.
constraints[-1].influence = 0
pose = obj.pose.bones[outer.name]
int_pose = obj.pose.bones[intermediate.name]
bpy.context.view_layer.update()
initial_rotation = int_pose.matrix.to_quaternion()
pose.rotation_mode = "XYZ"
pose.rotation_euler = (0.3, 0.4, 0.2)
pose.location = (0.2, -0.1, 0.4)
pose.scale = (1.3, 1.3, 1.3)
bpy.context.view_layer.update()
close(int_pose.head, pose.head)
close(int_pose.matrix.to_scale(), pose.matrix.to_scale())
assert int_pose.matrix.to_quaternion().rotation_difference(initial_rotation).angle < 1e-5
constraints[-1].influence = 1
bpy.context.view_layer.update()
assert int_pose.matrix.to_quaternion().rotation_difference(pose.matrix.to_quaternion()).angle < 1e-5
constraints[-1].influence = 0
root = obj.pose.bones["ROOT"]
root.rotation_mode = "XYZ"
root.rotation_euler.y = 0.5
bpy.context.view_layer.update()
assert int_pose.matrix.to_quaternion().rotation_difference(initial_rotation).angle > 0.1
close(int_pose.head, pose.head)
expect_error(obj)  # Repeated click cannot overwrite the reference pair.

# All six WORLD directions stay correct with a rotated, nonuniformly scaled rig.
for index, (axis, direction) in enumerate(socket.AXES.items()):
    obj = fixture("Axis" + axis, root_name=("root" if index % 2 else "Root"))
    obj.rotation_euler = (0.4, -0.2, 0.6)
    obj.scale = (1.2, 1.7, 0.8)
    obj.location = (2, 3, 4)
    bpy.context.view_layer.update()
    settings = obj.data.ozo_bone_socket
    settings.direction = axis
    settings.socket_length = 0.15
    settings.int_length = 0.03
    settings.use_collection = True
    settings.collection = "Existing MCH"
    if index % 2:
        bpy.ops.object.mode_set(mode="EDIT")
        select_source(obj)  # A selected head alone is sufficient.
    mode = obj.mode
    assert bpy.ops.ozo.create_socket() == {"FINISHED"}
    assert obj.mode == mode
    if mode == "EDIT":
        assert obj.data.edit_bones.active.name == "Controller.L.001"
        bpy.ops.object.mode_set(mode="POSE")
    for name in ("MCH_Socket_Controller.L", "MCH_INT_Socket_Controller.L"):
        bone = obj.data.bones[name]
        close((obj.matrix_world.to_3x3() @ (bone.tail_local - bone.head_local)).normalized(), direction)
        assert [c.name for c in bone.collections] == ["Existing MCH"]
    assert len(obj.data.bones) == 5

# Validation and complete rollback even if constraints were already created.
obj = fixture("Rollback")
real_add = socket.add_socket_constraints
def fail_after_constraints(obj, plan):
    real_add(obj, plan)
    raise RuntimeError("Injected failure after all constraints")
socket.add_socket_constraints = fail_after_constraints
expect_error(obj)
socket.add_socket_constraints = real_add
settings = obj.data.ozo_bone_socket
settings.root_bone = "Missing"
expect_error(obj)
settings.root_bone = "Controller.L.001"
expect_error(obj)
settings.root_bone = ""
obj.data.bones["ROOT"].name = "Global"
expect_error(obj)
settings.root_bone = "Global"
settings.rotation_follow = 0.75
assert bpy.ops.ozo.create_socket() == {"FINISHED"}
assert obj.pose.bones["MCH_INT_Socket_Controller.L"].constraints[-1].influence == 0.75

with tempfile.TemporaryDirectory(prefix="socket_", dir=ROOT / "tests") as directory:
    path = str(Path(directory) / "socket.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    obj = bpy.context.active_object
    assert obj.data.ozo_bone_socket.root_bone == "Global"
    assert [c.type for c in obj.pose.bones["MCH_INT_Socket_Controller.L"].constraints] == ["COPY_LOCATION", "COPY_SCALE", "COPY_ROTATION"]

obj = fixture("Unparented")
with edit_active_armature(bpy.context, obj) as bones:
    bones["Controller.L.001"].use_connect = False
    bones["Controller.L.001"].parent = None
assert bpy.ops.ozo.create_socket() == {"FINISHED"}
assert obj.data.bones["MCH_Socket_Controller.L"].parent is None

assert socket.socket_base("Control.001.L.002") == "Control.L"
assert bpy.types.Panel.bl_rna_get_subclass_py("OZO_PT_bone_controls").bl_label == "RIG Tools"
OZO_Tools.unregister()
assert not hasattr(bpy.types.Armature, "ozo_bone_socket")
OZO_Tools.register()
OZO_Tools.unregister()
print("OZO_SOCKET_PASS: head selection, world axes, hierarchy, ordered constraints, rotation isolation, collections, rollback, persistence")
