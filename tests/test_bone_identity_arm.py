"""Keep existing Arm instance identities and links intact when clearing copies."""
from pathlib import Path
exec(compile(Path(__file__).with_name("test_arm_blender.py").read_text("utf-8-sig").split("\nobj,s,names = run_full")[0], __file__, "exec"))
from OZO_Tools import bone_identity as utility

obj, settings, names = fixture("ArmCopiedIdentity")
first_three(obj)
record = next(iter(a.read_records(obj.data)["arms"].values()))
index = rig.index_bones(obj.data)
original = index[record["bones"]["fk_arm"]].name
old_id = obj.data.bones[original][rig.BONE_ID]
with edit_active_armature(bpy.context, obj) as bones:
    source = bones[original]
    copy = bones.new("NewController")
    copy.head, copy.tail, copy.roll = source.head.copy(), source.tail.copy(), source.roll
    copy.parent = source.parent
    copy[rig.BONE_ID] = old_id
for pose in obj.pose.bones:
    pose.select = pose.name == "NewController"
obj.data.bones.active = obj.data.bones["NewController"]
obj.data.ozo_bone_identity.original_bone = original
raw = obj.data[a.RECORD_KEY]
utility.clear_selected(bpy.context)
assert obj.data[a.RECORD_KEY] == raw
assert obj.data.bones[original][rig.BONE_ID] == old_id
assert rig.BONE_ID not in obj.data.bones["NewController"]
a.audit(obj, record, through=3)

# Clearing the actual generated parent would break the owned chain and is refused.
with edit_active_armature(bpy.context, obj) as bones:
    bones["NewController"][rig.BONE_ID] = old_id
for pose in obj.pose.bones:
    pose.select = pose.name == original
obj.data.bones.active = obj.data.bones[original]
obj.data.ozo_bone_identity.original_bone = "NewController"
try:
    utility.clear_selected(bpy.context)
except ValueError as error:
    assert "parent" in str(error).lower()
else:
    raise AssertionError("Must not retarget the existing Arm chain")
assert obj.data[a.RECORD_KEY] == raw
assert obj.data.bones[original][rig.BONE_ID] == old_id
OZO_Tools.unregister()
print("OZO_BONE_IDENTITY_ARM_PASS: copied Arm controller clears independently; actual instance parent cannot be detached")
