"""Automatic ID repair retains full staged Arm mapping after native duplication."""
from pathlib import Path
exec(compile(Path(__file__).with_name('test_arm_blender.py').read_text('utf-8-sig').split('\nobj,s,names = run_full')[0], __file__, 'exec'))
from OZO_Tools import bone_identity as utility, identity_repair as repair

obj, settings, names = fixture('AutoRepairArm')
first_three(obj)
record = next(iter(a.read_records(obj.data)['arms'].values()))
index = rig.index_bones(obj.data)
originals = {role: index[uid].name for role, uid in {**record['mapping'], **record['bones']}.items()}
# Duplicate each original independently; physical chain/Tweak links distinguish
# every original except free controls with no connected constraints yet.
roles = ['fk_arm', 'fk_forearm', 'switch_arm', 'source_arm', 'tweak_arm']
before = snapshot(obj)
raw = obj.data[a.RECORD_KEY]
with edit_active_armature(bpy.context, obj) as bones:
    for role in roles:
        source = bones[originals[role]]
        copy = bones.new('Copy_' + role)
        copy.head, copy.tail, copy.roll = source.head.copy(), source.tail.copy(), source.roll
        copy.parent = source.parent
        for key in repair.KEYS:
            if key in source:
                copy[key] = source[key]
result = utility.repair_duplicates(bpy.context)
assert result['count'] == len(roles) and not result['conflicts'], result
assert obj.data[a.RECORD_KEY] == raw
for role in roles:
    assert obj.data.bones[originals[role]][rig.BONE_ID] != obj.data.bones['Copy_' + role][rig.BONE_ID]
a.audit(obj, record, through=3)
# A free Pole copied before IK connection is truly indistinguishable. Keep both
# unchanged and report ambiguity; manual Original + selected copy can resolve it.
original = originals['pole']
with edit_active_armature(bpy.context, obj) as bones:
    old = bones[original]
    b = bones.new('NewPole')
    b.head, b.tail, b.roll = old.head.copy(), old.tail.copy(), old.roll
    b.parent = old.parent
    b[rig.BONE_ID] = old[rig.BONE_ID]
result = utility.repair_duplicates(bpy.context)
assert result['conflicts'] == 1 and result['count'] == 0, result
obj.data.ozo_bone_identity.original_bone = original
for p in obj.pose.bones:
    p.select = p.name == 'NewPole'
result = utility.repair_duplicates(bpy.context)
assert result['count'] == 1 and result['conflicts'] == 0, result
a.audit(obj, record, through=3)
OZO_Tools.unregister()
print('OZO_IDENTITY_REPAIR_ARM_PASS: shared/legacy Arm input markers, generated chains, ambiguous free Pole and manual resolution')
