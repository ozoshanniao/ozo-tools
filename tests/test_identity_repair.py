"""One-click repair on synthetic armatures, including both copied ID systems."""
from pathlib import Path
import json
import sys
import tempfile
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import OZO_Tools
from OZO_Tools import bone_identity as ui, identity_repair as repair
from OZO_Tools import bone_controls as bc, rotation_follow as rf, rig_common as rig
from OZO_Tools.bone_parenting import edit_active_armature

OZO_Tools.register()


def select(obj, names):
    for p in obj.pose.bones:
        p.select = p.name in names
    obj.data.bones.active = obj.data.bones.get(names[0]) if names else None


def fixture(label):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for o in bpy.context.selected_objects:
        o.select_set(False)
    obj = bpy.data.objects.new(label, bpy.data.armatures.new(label))
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    col = obj.data.collections.new('Working')
    obj.data.collections.active = col
    with edit_active_armature(bpy.context, obj) as bones:
        for i, name in enumerate(('Source', 'ORG_Chain', 'Properties', 'Other')):
            b = bones.new(name)
            b.head, b.tail = (i, 0, 0), (i, 1, 0)
            col.assign(b)
    bpy.ops.object.mode_set(mode='POSE')
    select(obj, ['ORG_Chain'])
    return obj


def duplicate(obj, source, name, constraints=False):
    with edit_active_armature(bpy.context, obj) as bones:
        old = bones[source]
        b = bones.new(name)
        b.head, b.tail, b.roll = old.head.copy(), old.tail.copy(), old.roll
        b.parent = old.parent
        for key in repair.KEYS:
            if key in old:
                b[key] = old[key]
        b['UserData'] = 17
    if constraints:
        for c in list(obj.pose.bones[source].constraints):
            new = obj.pose.bones[name].constraints.new(c.type)
            new.name = c.name
            if hasattr(c, 'target'):
                new.target, new.subtarget = c.target, c.subtarget


def state(obj):
    return {
        'geometry': {b.name: (rig.rest_geometry(b), b.parent.name if b.parent else None, b.use_connect,
                              b.use_deform, tuple(c.name for c in b.collections)) for b in obj.data.bones},
        'constraints': [(p.name, c.name, c.type, getattr(c, 'subtarget', None), c.influence)
                        for p in obj.pose.bones for c in p.constraints],
        'drivers': [(f.data_path, f.driver.expression) for f in (obj.animation_data.drivers if obj.animation_data else [])],
        'records': {k: obj.data.get(k) for k in repair.RECORD_KEYS},
    }


def assert_repaired(obj, expected):
    before = state(obj)
    result = ui.repair_duplicates(bpy.context)
    assert result['count'] == expected and result['conflicts'] == 0, result
    assert state(obj) == before
    assert ui.repair_duplicates(bpy.context)['count'] == 0
    return result


# Legacy FK duplicate blocks an unrelated selected chain: repair both old and
# common markers on the same Master copy, leaving recorded FK identity intact.
obj = fixture('LegacyAndCommon')
bc.create_tweak(bpy.context)
bc.create_fk(bpy.context)
fk = 'Chain'
select(obj, [fk])
s = obj.data.ozo_rotation_follow
s.rotation_source, s.property_bone = 'Source', 'Properties'
rf.load_selected(bpy.context)
rf.connect_rotation(bpy.context)
original = {k: obj.data.bones[fk][k] for k in repair.KEYS}
duplicate(obj, fk, 'Master')
# Rename the original: matching by recorded labels would now be wrong.
obj.data.bones[fk].name = 'RenamedFK'
select(obj, ['Other'])
result = assert_repaired(obj, 1)
assert result['markers'] == 2
assert all(obj.data.bones['RenamedFK'][k] == v for k, v in original.items())
assert all(obj.data.bones['Master'][k] != v for k, v in original.items())
assert obj.data.bones['Master']['UserData'] == 17

# A copied FK can already have a DIFFERENT valid shared identity as the source
# of a new RF binding. That new binding cannot claim its stale legacy ID.
duplicate(obj, 'RenamedFK', 'NewMaster')
obj.data.bones['NewMaster'][rig.BONE_ID] = 'new-master-valid-shared-id'
select(obj, ['Other'])
s.rotation_source = 'NewMaster'
rf.load_selected(bpy.context)
rf.connect_rotation(bpy.context)
result = assert_repaired(obj, 1)
assert result['markers'] == 1
assert obj.data.bones['NewMaster'][rig.BONE_ID] == 'new-master-valid-shared-id'
assert obj.data.bones['RenamedFK'][bc.ID_KEY] == original[bc.ID_KEY]

# MCH copied for an extra collision layer above the original, matching the live
# report. The recorded controller parent and owned constraint identify the MCH.
obj = fixture('CollisionLayer')
s = obj.data.ozo_rotation_follow
s.rotation_source, s.property_bone, s.mode = 'Source', 'Properties', 'MCH'
rf.load_selected(bpy.context)
rf.create_mch(bpy.context)
rf.connect_rotation(bpy.context)
rf.connect_property(bpy.context)
mch = rig.index_bones(obj.data)[next(iter(rf.read_records(obj.data)['bindings'].values()))['mch']].name
uid = obj.data.bones[mch][rig.BONE_ID]
duplicate(obj, mch, 'MCH_Collide', constraints=False)
with edit_active_armature(bpy.context, obj) as bones:
    bones[mch].parent = bones['MCH_Collide']
duplicate(obj, 'Source', 'NewSource')
duplicate(obj, 'Properties', 'NewProperties')
select(obj, ['Other'])
assert_repaired(obj, 3)
assert obj.data.bones[mch][rig.BONE_ID] == uid
rig.index_bones(obj.data)

# No constraints connected yet: actual controller parent still identifies MCH.
obj = fixture('Intermediate')
s = obj.data.ozo_rotation_follow
s.rotation_source, s.mode = 'Source', 'MCH'
rf.load_selected(bpy.context)
rf.create_mch(bpy.context)
mch = rig.index_bones(obj.data)[next(iter(rf.read_records(obj.data)['bindings'].values()))['mch']].name
duplicate(obj, mch, 'CopyMCH')
assert_repaired(obj, 1)
rf.connect_rotation(bpy.context)

# Unbound duplicate groups: all members receive fresh independent IDs. Cached
# input/affected rows for the re-keyed copies must not retain the old mapping.
obj = fixture('Unbound')
s = obj.data.ozo_rotation_follow
s.rotation_source = 'Source'
rf.load_selected(bpy.context)
old = obj.data.bones['ORG_Chain'][rig.BONE_ID]
duplicate(obj, 'ORG_Chain', 'Copy')
obj.data.bones['Copy'][bc.ID_KEY] = obj.data.bones['ORG_Chain'][bc.ID_KEY] = 'legacy-unbound'
assert_repaired(obj, 2)
assert not s.affected
assert obj.data.bones['ORG_Chain'][rig.BONE_ID] != old
assert len({b.get(rig.BONE_ID) for b in obj.data.bones if b.get(rig.BONE_ID)}) == 3

# Fully indistinguishable Direct copies: do not guess using name, list order,
# current selection or the original's unchanged stored label.
obj = fixture('Ambiguous')
s = obj.data.ozo_rotation_follow
s.rotation_source = 'Source'
rf.load_selected(bpy.context)
rf.connect_rotation(bpy.context)
duplicate(obj, 'ORG_Chain', 'ControllerCopy', constraints=True)
before_ids = {b.name: b.get(rig.BONE_ID) for b in obj.data.bones}
result = ui.repair_duplicates(bpy.context)
assert result['count'] == 0 and result['conflicts'] == 1, result
assert {b.name: b.get(rig.BONE_ID) for b in obj.data.bones} == before_ids
obj.data.ozo_bone_identity.original_bone = 'ORG_Chain'
select(obj, ['ControllerCopy'])
assert_repaired(obj, 1)

# Unknown persistent references are protected; unrelated repairable groups can
# still be repaired, and the remaining conflict is visible in Details.
duplicate(obj, 'Source', 'SourceCopy')
source_id = obj.data.bones['Source'][rig.BONE_ID]
obj.data['ozo_future_records'] = json.dumps({'source': source_id})
duplicate(obj, 'ControllerCopy', 'FreeCopy')
result = ui.repair_duplicates(bpy.context)
assert result['count'] == 2 and result['conflicts'] == 1, result
assert 'unknown record' in result['details']
assert obj.data.bones['SourceCopy'][rig.BONE_ID] == source_id

# Inject failure after both types of marker have been touched. Restore IDs and
# cached settings exactly, without changing geometry/records/driver signatures.
obj = fixture('Rollback')
for key in repair.KEYS:
    obj.data.bones['Other'][key] = 'unbound-' + key
duplicate(obj, 'Other', 'OtherCopy')
before = {(b.name, k): b.get(k) for b in obj.data.bones for k in repair.KEYS}
settings_before = ui.settings_snapshot(obj.data)
old_apply = repair.apply_change
calls = 0
def fail(data, key, name, uid):
    global calls
    old_apply(data, key, name, uid)
    calls += 1
    if calls == 3:
        raise RuntimeError('injected repair failure')
repair.apply_change = fail
try:
    ui.repair_duplicates(bpy.context)
except RuntimeError:
    pass
else:
    raise AssertionError('Expected rollback')
finally:
    repair.apply_change = old_apply
assert {(b.name, k): b.get(k) for b in obj.data.bones for k in repair.KEYS} == before
assert ui.settings_snapshot(obj.data) == settings_before

# Native Edit Mode operator, Undo/Redo, no implicit file save, save/reopen.
bpy.context.preferences.edit.use_global_undo = True
bpy.ops.ed.undo_push(message='Before Repair')
label = obj.name
bpy.ops.object.mode_set(mode='EDIT')
assert bpy.ops.ozo.repair_duplicate_bone_identities() == {'FINISHED'}
assert obj.mode == 'EDIT'
assert obj.data.edit_bones['Other'][rig.BONE_ID] != obj.data.edit_bones['OtherCopy'][rig.BONE_ID]
bpy.ops.object.mode_set(mode='POSE')
bpy.ops.ed.undo_push(message='After Repair')
bpy.ops.ed.undo()
obj = bpy.data.objects[label]
assert obj.data.bones['Other'][rig.BONE_ID] == obj.data.bones['OtherCopy'][rig.BONE_ID]
bpy.ops.ed.redo()
obj = bpy.data.objects[label]
assert obj.data.bones['Other'][rig.BONE_ID] != obj.data.bones['OtherCopy'][rig.BONE_ID]
with tempfile.TemporaryDirectory(prefix='identity_repair_', dir=ROOT / 'tests') as directory:
    path = str(Path(directory) / 'synthetic.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    assert ui.repair_duplicates(bpy.context)['count'] == 0
OZO_Tools.unregister()
print('OZO_IDENTITY_REPAIR_PASS: legacy/common duplicates, recorded links, renamed original, collision layer, source/property driver, intermediate MCH, ambiguity/manual, unknown references, rollback, Edit Mode, Undo/Redo, persistence')
