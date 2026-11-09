"""Arm acceptance on synthetic rigs only. Run with --factory-startup --background."""
from pathlib import Path
import json
import math
import sys
import tempfile
import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import OZO_Tools
from OZO_Tools import arm as a, rig_common as rig, bone_controls as bc
from OZO_Tools.bone_parenting import edit_active_armature

OZO_Tools.register()
CASES = []
METRICS = []


def fixture(label, side=".L", roll=0, turn=0, straight=False, manual=False):
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    for item in bpy.context.selected_objects:
        item.select_set(False)
    obj = bpy.data.objects.new(label, bpy.data.armatures.new(label))
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    col = obj.data.collections.new("Working")
    obj.data.collections.new("FK")
    obj.data.collections.new("IK")
    obj.data.collections.new("Controls")
    obj.data.collections.active = col
    sign = -1 if side == ".R" else 1
    transform = Matrix.Rotation(turn, 4, Vector((0.4, 0.1, 0.8)))
    coords = [Vector((0,0,0)), Vector((0 if straight else sign * 0.65,2,0)), Vector((0,4,0)), Vector((0,4.7,0))]
    coords = [transform @ p for p in coords]
    names = [f"ORG_{r}{side}" for r in ("Arm_01", "Forarm", "Hand")]
    with edit_active_armature(bpy.context, obj) as edits:
        for name, head, tail in (("ROOT", (0,0,-2),(0,0,-1)), ("Properties",(2,0,0),(2,0,1))):
            b = edits.new(name)
            b.head, b.tail = head, tail
            col.assign(b)
        parent = edits["ROOT"]
        for i, name in enumerate(names):
            b = edits.new(name)
            b.head, b.tail = coords[i], coords[i+1]
            b.roll = roll
            b.parent = parent
            b.use_connect = bool(i)
            if turn:
                # Rotate complete rest frames, not only head/tail.
                b.transform(transform.inverted())
                b.transform(transform)
            col.assign(b)
            parent = b
    bpy.ops.object.mode_set(mode="POSE")
    for p in obj.pose.bones:
        p.select = p.name in names
    obj.data.bones.active = obj.data.bones[names[0]]
    bc.create_tweak(bpy.context)
    settings = obj.data.ozo_arm
    a.load_tweak_mapping(bpy.context)
    settings.switch_use_collection = True
    settings.switch_collection = "Working"
    for group, col_name in (("fk","FK"),("ik","IK"),("control","Controls")):
        setattr(settings, group + "_use_collection", True)
        setattr(settings, group + "_collection", col_name)
    settings.bend_axis = "Z"
    return obj, settings, names


def rec(obj):
    return a.read_records(obj.data)["arms"][obj.data.ozo_arm.active_id]


def bones(obj):
    return a.resolved(obj, rec(obj))


def eval_obj(obj):
    obj.update_tag(refresh={"OBJECT"})
    bpy.context.view_layer.update()
    return obj.evaluated_get(bpy.context.evaluated_depsgraph_get())


def snapshot(obj):
    return {
        "bones": {b.name: (b.parent.name if b.parent else None, b.use_connect, rig.rest_geometry(b), b.get(rig.BONE_ID))
                  for b in obj.data.bones},
        "records": obj.data.get(a.RECORD_KEY),
        "constraints": [(p.name, [(c.name, c.type, getattr(c, "subtarget", ""), getattr(c,"pole_angle",None)) for c in p.constraints])
                        for p in obj.pose.bones],
        "drivers": [(f.data_path, f.driver.expression) for f in (obj.animation_data.drivers if obj.animation_data else [])],
        "pose": {p.name: (tuple(p.location),tuple(p.rotation_quaternion),tuple(p.rotation_euler),tuple(p.scale),
                         tuple(getattr(p,k) for k in a.POSE_FIELDS), dict(p.items())) for p in obj.pose.bones},
        "frame": (bpy.context.scene.frame_current, bpy.context.scene.frame_subframe),
    }


def reject(fn, obj, message=""):
    mode = obj.mode
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="OBJECT")
    before = snapshot(obj)
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")
    try:
        fn(bpy.context)
    except (ValueError, RuntimeError) as error:
        print("EXPECTED", error)
        assert message.lower() in str(error).lower(), str(error)
    else:
        raise AssertionError("Expected rejection: " + fn.__name__)
    assert obj.mode == mode
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="OBJECT")
    assert snapshot(obj) == before, "Rollback failed"
    if mode == "EDIT":
        bpy.ops.object.mode_set(mode="EDIT")


def first_three(obj):
    a.create_switch(bpy.context)
    a.create_chains(bpy.context)
    a.create_controls(bpy.context)


def run_full(side, roll, turn, objturn):
    obj,s,names = fixture("Calibration" + side + str(roll) + str(turn), side, roll, turn)
    obj.rotation_euler = (objturn, -objturn * 0.3, objturn * 0.5)
    obj.scale = (1.7,)*3
    original = {n: rig.rest_geometry(obj.data.bones[n]) for n in names}
    original_constraints = {n:[(c.name,c.type,c.subtarget) for c in obj.pose.bones[n].constraints] for n in names}
    first_three(obj)
    b = bones(obj)
    assert b["tip"].parent == b["switch_hand"]
    assert b["tweak_hand"].parent == b["switch_hand"]
    assert b["switch_arm"].parent.name == "ROOT"
    for group in ("switch", "fk", "ik"):
        assert b[group + "_arm"].parent.name == "ROOT"
    assert b["ik_forearm"].use_connect
    assert not b["ik_hand"].use_connect
    assert len(rec(obj)["bones"]) == 12
    for role in a.ROLES:
        assert len(b["fk_" + role].children) == (0 if role == "hand" else 1)
    world_y = (obj.matrix_world.to_3x3() @ (b["pole"].tail_local - b["pole"].head_local)).normalized()
    assert world_y.dot(Vector((0,1,0))) > 0.999999
    assert abs((b["pole"].head_local - b["ik_forearm"].head_local).length - b["ik_arm"].length) < 1e-5
    a.connect_ik(bpy.context)
    a.match_rest_bend(bpy.context)
    r = rec(obj)
    METRICS.append({"side": side,"roll": roll,"turn":turn,"object_turn":objturn,**r["calibration"]})
    ev = eval_obj(obj)
    b = bones(obj)
    assert (ev.pose.bones[b["ik_forearm"].name].head - b["ik_forearm"].head_local).length < 0.01
    assert (ev.pose.bones[b["ik_hand"].name].matrix.translation - ev.pose.bones[b["hand_control"].name].matrix.translation).length < 1e-5
    # Reposition Pole in edit mode: do not let calibration move or reorient it.
    pole_name = b["pole"].name
    with edit_active_armature(bpy.context, obj) as edits:
        edits[pole_name].translate(Vector((0.13, -0.15, 0.8)))
    before_geometry = {k:rig.rest_geometry(v) for k,v in bones(obj).items()}
    before_channels = {p.name:p.matrix_basis.copy() for p in obj.pose.bones}
    a.match_rest_bend(bpy.context)
    assert before_geometry == {k:rig.rest_geometry(v) for k,v in bones(obj).items()}
    assert all(p.matrix_basis == before_channels[p.name] for p in obj.pose.bones)
    a.connect_switch(bpy.context)
    assert obj.pose.bones["Properties"]["Arm_FK_IK" + side] == 0
    b = bones(obj)
    # Deliberately make FK differ, then verify three actual Switch matrices in each mode.
    p = obj.pose.bones[b["fk_arm"].name]
    p.rotation_mode = "XYZ"
    p.rotation_euler.y = 0.15
    for value, group in ((0,"fk"),(1,"ik")):
        obj.pose.bones["Properties"]["Arm_FK_IK"+side] = value
        ev = eval_obj(obj)
        for role in a.ROLES:
            sw = ev.pose.bones[b["switch_"+role].name].matrix
            target = ev.pose.bones[b[group+"_"+role].name].matrix
            assert max(abs(sw[i][j]-target[i][j]) for i in range(4) for j in range(4)) < 2e-4
            cs = obj.pose.bones[b["switch_"+role].name].constraints
            assert cs[0].name.startswith("OZO FK") and cs[1].name.startswith("OZO IK")
    for n in names:
        assert rig.same_geometry(obj.data.bones[n], original[n])
        assert [(c.name,c.type,c.subtarget) for c in obj.pose.bones[n].constraints] == original_constraints[n]
    for fn in (a.create_switch, a.create_chains, a.create_controls, a.connect_ik, a.connect_switch):
        before = len(obj.data.bones), len(rec(obj)["constraints"])
        fn(bpy.context)
        assert (len(obj.data.bones),len(rec(obj)["constraints"])) == before
    # Numerical update is explicit.
    s.arm_stretch,s.forearm_stretch,s.enable_stretch = 0.02,0.03,False
    a.update_ik(bpy.context)
    assert obj.pose.bones[b["ik_arm"].name].ik_stretch == s.arm_stretch
    assert not next(c for c in obj.pose.bones[b["ik_forearm"].name].constraints if c.type=="IK").use_stretch
    return obj,s,names


obj,s,names = run_full(".L",0,0,0.4)
CASES.append("Five stages, clean rest chains, collections, original source preservation, evaluated FK/IK modes, no duplicates and explicit IK update")
for args in ((".R",0,0,0), (".L",0.7,0,0), (".R",-0.85,0.55,0.6), ("",1.1,0.7,0)):
    obj,s,names = run_full(*args)
CASES.append("Evaluated Match Rest Bend: left/right/no suffix, arbitrary rolls and armature/object orientations, repositioned Pole, untouched geometry/channels")

# Socket-like parent inserted after Switch must be used at the time of stage 2.
obj,s,names = fixture("Reparent")
a.create_switch(bpy.context)
with edit_active_armature(bpy.context,obj) as edits:
    b=edits.new("ManualSocket")
    b.head,b.tail=(0,0,-1),(0,0,0)
    b.parent=edits["ROOT"]
    edits["MCH_Switch_Arm_01.L"].parent=b
a.create_chains(bpy.context)
assert all(bones(obj)[g+"_arm"].parent.name=="ManualSocket" for g in ("switch","fk","ik"))
s.create_visual=False
s.pole_distance=3
s.flip_direction=True
a.create_controls(bpy.context)
assert "visual" not in rec(obj)["bones"]
a.connect_ik(bpy.context)
a.match_rest_bend(bpy.context)
s.pole_distance=2.5
s.pole_length=0.6
a.update_controls(bpy.context)
assert abs(bones(obj)["pole"].length-0.6)<1e-5
CASES.append("Current Switch parent after manual Socket, no visual, Distance/Flip and explicit Pole update")

# Existing integer property, preserve current value, UI metadata and animation.
p=obj.pose.bones["Properties"]
p["Existing"]=1
p.id_properties_ui("Existing").update(min=0,max=1,description="0=FK, 1=IK",default=1)
p.keyframe_insert(data_path='["Existing"]',frame=1)
s.property_mode,s.property_name,s.confirm_semantics="EXISTING","Existing",True
ui_before=p.id_properties_ui("Existing").as_dict()
a.connect_switch(bpy.context)
assert p["Existing"]==1 and p.id_properties_ui("Existing").as_dict()==ui_before
assert rec(obj)["link"]["name"]=="Existing"
CASES.append("Existing integer switch property retains value/range/description/default/animation")

# Bone renames continue through identity records; deleted/replaced bones fail.
for role in ("source_arm","tweak_forearm","switch_arm","fk_hand","hand_control","pole"):
    bones(obj)[role].name="Renamed_"+role
a.check_instance(bpy.context)
a.load_instance(bpy.context)
a.create_switch(bpy.context)
obj.data.bones["Properties"].name="PropsRenamed"
a.check_instance(bpy.context)
obj.pose.bones[bones(obj)["switch_arm"].name].constraints[0].name="UserRenamed"
reject(a.check_instance,obj,"constraint")
CASES.append("Renamed sources/tweaks/generated bones/property carrier survive; constraint edits detected")

# Degenerate/invalid/missing mappings and transform rejection.
obj,s,names=fixture("Straight",straight=True)
s.pole_direction_mode="REST"
a.create_switch(bpy.context)
a.create_chains(bpy.context)
reject(a.create_controls,obj,"nearly straight")
s.pole_direction_mode="EXPLICIT"
s.pole_direction=(0,0,1)
a.create_controls(bpy.context)
a.connect_ik(bpy.context)
reject(a.match_rest_bend,obj,"nearly straight")
obj,s,names=fixture("BadPole")
first_three(obj)
a.connect_ik(bpy.context)
with edit_active_armature(bpy.context,obj) as edits:
    b=edits[bones(obj)["pole"].name]
    b.head,b.tail=(0,2,0),(0,2,1)
reject(a.match_rest_bend,obj,"Pole")
obj.scale=(1,2,1)
reject(a.match_rest_bend,obj,"uniform")
CASES.append("Straight chains require explicit positioning; calibration degeneracy and unsupported object scale reject with no mutation")

obj,s,names=fixture("Conflicts")
s.tip=s.source_hand
reject(a.create_switch,obj,"distinct")
s.tip="Hand_Tip_Tweak.L"
with edit_active_armature(bpy.context,obj) as edits:
    b=edits.new("MCH_Switch_Arm_01.L")
    b.head,b.tail=(1,0,0),(1,1,0)
reject(a.create_switch,obj,"exists")
with edit_active_armature(bpy.context,obj) as edits:
    edits.remove(edits["MCH_Switch_Arm_01.L"])
# Existing driver path for a proposed new bone is not adopted.
obj.animation_data_create().drivers.new('pose.bones["MCH_Switch_Arm_01.L"].location', index=0)
reject(a.create_switch,obj,"animation")
obj.animation_data.drivers.remove(obj.animation_data.drivers[0])
s.parent_mode,s.switch_parent="BONE",s.source_arm
reject(a.create_switch,obj,"cycle")
s.parent_mode="NONE"
a.create_switch(bpy.context)
assert bones(obj)["switch_arm"].parent is None
a.create_chains(bpy.context)
a.create_controls(bpy.context)
s.bend_axis="NONE"
reject(a.connect_ik,obj,"Bend Axis")
s.bend_axis="Z"
CASES.append("Explicit mapping, names/animation paths, parent cycles, None parent and required Bend Axis")

# Inject partial failures for each write class.
obj,s,names=fixture("RollbackStructure")
old_make=a.make_bone
counter=[0]
def fail_make(*args,**kwargs):
    out=old_make(*args,**kwargs)
    counter[0]+=1
    if counter[0]==2:
        raise RuntimeError("Injected partial bone creation failure")
    return out
a.make_bone=fail_make
reject(a.create_switch,obj,"Injected")
a.make_bone=old_make
first_three(obj)
old_new=a.ArmTransaction.new_constraint
counter[0]=0
def fail_constraint(self,*args):
    out=old_new(self,*args)
    counter[0]+=1
    if counter[0]==2:
        raise RuntimeError("Injected partial constraint failure")
    return out
a.ArmTransaction.new_constraint=fail_constraint
reject(a.connect_ik,obj,"Injected")
a.ArmTransaction.new_constraint=old_new
a.connect_ik(bpy.context)
counter[0]=0
a.ArmTransaction.new_constraint=fail_constraint
reject(a.connect_switch,obj,"Injected")
a.ArmTransaction.new_constraint=old_new
assert "Arm_FK_IK.L" not in obj.pose.bones["Properties"]
CASES.append("Injected partial bone/parent, IK settings/constraints and new switch property/driver failures roll back")

# Save/reopen after each stage and continue; no original character is loaded.
obj,s,names=fixture("Roundtrip")
with tempfile.TemporaryDirectory(prefix="arm_roundtrip_",dir=ROOT/"tests") as directory:
    path=str(Path(directory)/"synthetic.blend")
    for fn in (a.create_switch,a.create_chains,a.create_controls,a.connect_ik,a.connect_switch):
        fn(bpy.context)
        raw=obj.data[a.RECORD_KEY]
        label=obj.name
        bpy.ops.wm.save_as_mainfile(filepath=path)
        bpy.ops.wm.open_mainfile(filepath=path)
        obj=bpy.data.objects[label]
        s=obj.data.ozo_arm
        assert obj.data[a.RECORD_KEY]==raw
        a.check_instance(bpy.context)
        fn(bpy.context)
    # Register/unregister doesn't discard saved intermediate state.
    OZO_Tools.unregister()
    OZO_Tools.register()
    assert rec(obj)["steps"]==[True]*5
    a.check_instance(bpy.context)
CASES.append("Save/reopen at all five stages, idempotent continuation, register/unregister preserves records")

# Native Undo/Redo for all five stage operators.
obj,s,names=fixture("UndoArm")
label=obj.name
bpy.context.preferences.edit.use_global_undo=True
for key, count in (("switch",3),("chains",6),("controls",3),("connect_ik",0),("connect_switch",0)):
    bpy.ops.ed.undo_push(message="Before Arm "+key)
    before=len(obj.data.bones)
    assert getattr(bpy.ops.ozo,"arm_"+key)()=={"FINISHED"}
    after_records=obj.data[a.RECORD_KEY]
    bpy.ops.ed.undo_push(message="After Arm "+key)
    bpy.ops.ed.undo()
    obj=bpy.data.objects[label]
    assert len(obj.data.bones)==before
    bpy.ops.ed.redo()
    obj=bpy.data.objects[label]
    assert len(obj.data.bones)==before+count and obj.data[a.RECORD_KEY]==after_records
CASES.append("Real Blender Undo/Redo on every construction/connection stage")

assert not any(o.name.startswith("__OZO_Arm_Calibration") for o in bpy.data.objects)
assert not any(d.name.startswith("__OZO_Arm_Calibration") for d in bpy.data.armatures)
OZO_Tools.unregister()
report={"status":"PASS","blender":bpy.app.version_string,"cases":CASES,"calibration_metrics":METRICS}
(ROOT/"outputs"/"arm_test_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print("OZO_ARM_PASS",json.dumps(report,ensure_ascii=False))
