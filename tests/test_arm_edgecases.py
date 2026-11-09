"""Additional Arm integration/conflict/rollback tests on disposable synthetic rigs."""
from pathlib import Path
exec(compile((Path(__file__).with_name("test_arm_blender.py")).read_text("utf-8-sig").split("\nobj,s,names = run_full")[0], __file__, "exec"))
CASES=[]


def reject_type_property(value, metadata, fragment):
    obj,s,_=fixture("PropertyConflict")
    first_three(obj)
    a.connect_ik(bpy.context)
    pose=obj.pose.bones["Properties"]
    pose["Test"]=value
    if metadata:
        pose.id_properties_ui("Test").update(**metadata)
    s.property_mode,s.property_name,s.confirm_semantics="EXISTING","Test",True
    reject(a.connect_switch,obj,fragment)


for value,meta,fragment in (
    (0.0,{"min":0.0,"max":1.0},"integer"),
    (True,None,"integer"),
    (1,{"min":0,"max":2},"range"),
    (0,{"min":0,"max":1,"description":"0=IK, 1=FK"},"reversed"),
    (2,{"min":0,"max":1},"integer")):
    reject_type_property(value,meta,fragment)
CASES.append("Existing property rejects float/bool/bad range/reversed semantics/out-of-range integer without mutation")

obj,s,names=fixture("Manual")
# Remove native Tweak records/identities: Arm must only need explicit role mappings.
del obj.data[bc.RECORD_KEY]
for bone in obj.data.bones:
    if bc.ID_KEY in bone:
        del bone[bc.ID_KEY]
for field in a.INPUTS:
    setattr(s,field+"_id","")
    setattr(s,field+"_label","")
obj.pose.bones[names[0]]["KeepMe"]=2.5
obj.pose.bones[names[0]].driver_add('["KeepMe"]').driver.expression="2.5"
obj.pose.bones[names[0]].rotation_mode="XYZ"
obj.pose.bones[names[0]].keyframe_insert(data_path="rotation_euler",frame=1)
original_curves=[(c.data_path,c.driver.expression) for c in obj.animation_data.drivers]
a.create_switch(bpy.context)
# Step 2 copies the adjusted Switch, never the original Tweak length or children.
with edit_active_armature(bpy.context,obj) as edits:
    edits[bones(obj)["switch_hand"].name].roll+=0.35
a.create_chains(bpy.context)
b=bones(obj)
assert abs(b["ik_hand"].length-b["source_hand"].length)<1e-5
assert rig.same_geometry(b["fk_hand"],rig.rest_geometry(b["switch_hand"]))
assert original_curves==[(c.data_path,c.driver.expression) for c in obj.animation_data.drivers]
a.create_controls(bpy.context)
a.connect_ik(bpy.context)
# Target moved within reach + rotated: calibration probes the actual target.
p=obj.pose.bones[bones(obj)["hand_control"].name]
p.location=(0.15,-0.2,0.13)
p.rotation_mode="XYZ"
p.rotation_euler=(0.2,0.1,-0.25)
a.match_rest_bend(bpy.context)
assert rec(obj)["calibration"]["live_direction_dot"]>0.9999
ev=eval_obj(obj)
b=bones(obj)
hand=ev.pose.bones[b["ik_hand"].name].matrix
target=ev.pose.bones[b["hand_control"].name].matrix
assert max(abs(hand[i][j]-target[i][j]) for i in range(4) for j in range(4))<2e-5
# Pole visual starts at evaluated elbow, ends at Pole, with no feedback into IK.
v=ev.pose.bones[b["visual"].name]
assert (v.head-ev.pose.bones[b["ik_forearm"].name].head).length<2e-5
assert (v.tail-ev.pose.bones[b["pole"].name].head).length<2e-5
# Native stretch switches actually change the evaluated reach.
p.location=(0,3,0)
s.enable_stretch=True
s.arm_stretch,s.forearm_stretch=0.3,0.2
a.update_ik(bpy.context)
ev=eval_obj(obj)
stretched=(ev.pose.bones[b["ik_forearm"].name].tail-ev.pose.bones[b["hand_control"].name].head).length
s.enable_stretch=False
a.update_ik(bpy.context)
ev=eval_obj(obj)
unstretched=(ev.pose.bones[b["ik_forearm"].name].tail-ev.pose.bones[b["hand_control"].name].head).length
assert stretched<1e-3 and unstretched>0.5,(stretched,unstretched)
reject(a.match_rest_bend,obj,"unreachable")
CASES.append("Manual mapping without OZO Tweak records; source animation/drivers retained; edited Switch copied; actual moved target calibration; rotated hand, visual endpoints and evaluated stretch")

# The shoulder remains free; Bend Axis limits only the elbow.
s.bend_axis="X"
a.update_ik(bpy.context)
for role in ("arm","forearm"):
    p=obj.pose.bones[bones(obj)["ik_"+role].name]
    assert (p.lock_ik_x,p.lock_ik_y,p.lock_ik_z)==((False,False,False) if role=="arm" else (False,True,True))
CASES.append("Explicit elbow Bend Axis X changes hinge locks while shoulder XYZ remains free")

# Numeric updates restore both old constraints and old bone settings if commit fails.
obj,s,names=fixture("UpdateRollback")
first_three(obj)
a.connect_ik(bpy.context)
s.arm_stretch,s.forearm_stretch,s.pole_angle=0.2,0.3,1.2
old_save=a.save_records
def fail_save(*args):
    raise RuntimeError("Injected record commit failure")
a.save_records=fail_save
reject(a.update_ik,obj,"Injected")
a.save_records=old_save

# Partial failures after each structure creation phase and after a live driver exists.
for stage in (2,3):
    obj,s,names=fixture("RollbackStage"+str(stage))
    a.create_switch(bpy.context)
    if stage==3:
        a.create_chains(bpy.context)
    old_make=a.make_bone
    counter=[0]
    def fail_make(*args,**kwargs):
        out=old_make(*args,**kwargs)
        counter[0]+=1
        if counter[0]==2:
            raise RuntimeError("Injected stage structure failure")
        return out
    a.make_bone=fail_make
    reject(a.create_chains if stage==2 else a.create_controls,obj,"Injected")
    a.make_bone=old_make
obj,s,names=fixture("DriverRollback")
first_three(obj)
a.connect_ik(bpy.context)
old_new=a.ArmTransaction.new_constraint
counter=[0]
def fail_new(self,*args):
    out=old_new(self,*args)
    counter[0]+=1
    if counter[0]==4:
        raise RuntimeError("Injected after first switch driver")
    return out
a.ArmTransaction.new_constraint=fail_new
reject(a.connect_switch,obj,"Injected")
a.ArmTransaction.new_constraint=old_new
assert not obj.animation_data or not obj.animation_data.drivers
CASES.append("Failed numeric commit, stage 2/3 partial structure, and stage 5 after first driver restore all touched data")

# Incomplete / externally edited mechanisms are never rebuilt or adopted.
obj,s,names=fixture("Missing")
first_three(obj)
pole=bones(obj)["pole"].name
with edit_active_armature(bpy.context,obj) as edits:
    edits.remove(edits[pole])
    new=edits.new(pole)
    new.head,new.tail=(1,0,0),(1,1,0)
reject(a.create_controls,obj,"Missing or replaced")
obj,s,names=fixture("RestChanged")
a.create_switch(bpy.context)
with edit_active_armature(bpy.context,obj) as edits:
    edits[names[2]].roll+=0.1
reject(a.create_chains,obj,"Source rest")
obj,s,names=fixture("JointGap")
a.create_switch(bpy.context)
with edit_active_armature(bpy.context,obj) as edits:
    edits[bones(obj)["switch_forearm"].name].head.x+=0.1
reject(a.create_chains,obj,"do not coincide")
obj,s,names=fixture("Foreign")
first_three(obj)
p=obj.pose.bones[bones(obj)["ik_arm"].name]
p.constraints.new("COPY_ROTATION")
reject(a.connect_ik,obj,"user constraints")
CASES.append("Same-name replacement, source rest edits, noncoincident joints and foreign mechanisms reject instead of rebuilding")

# Ambiguous / explicit root, collection conflict, generated ancestor dependency cycle.
obj,s,names=fixture("Roots")
a.create_switch(bpy.context)
a.create_chains(bpy.context)
with edit_active_armature(bpy.context,obj) as edits:
    b=edits.new("root")
    b.head,b.tail=(0,0,-4),(0,0,-3)
reject(a.create_controls,obj,"Root explicitly")
s.root="ROOT"
s.control_collection="MissingCollection"
reject(a.create_controls,obj,"collection")
s.control_collection="Controls"
a.create_controls(bpy.context)
with edit_active_armature(bpy.context,obj) as edits:
    edits[bones(obj)["hand_control"].name].parent=edits[bones(obj)["ik_arm"].name]
reject(a.connect_ik,obj,"cycle")
CASES.append("Ambiguous ROOT, missing collection and IK-chain implicit dependency cycles detected")

# Shared data and singular object transforms.
obj,s,names=fixture("ReadOnly")
copy=bpy.data.objects.new("Shared",obj.data)
bpy.context.scene.collection.objects.link(copy)
assert not bpy.ops.ozo.arm_switch.poll()
reject(a.create_switch,obj,"single-user")
bpy.data.objects.remove(copy,do_unlink=True)
obj.scale=(1,0,1)
reject(a.create_switch,obj,"singular")
CASES.append("Shared data and singular transform reject before construction")

# Edit and multi-armature mode/selection restoration.
obj,s,names=fixture("Modes")
other,_,_=fixture("OtherModes")
bpy.ops.object.mode_set(mode="OBJECT")
other.select_set(True)
obj.select_set(True)
bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode="EDIT")
for item in (obj,other):
    for b in item.data.edit_bones:
        b.select=b.select_head=b.select_tail=False
    b=item.data.edit_bones[names[0]]
    b.select_head=True
    item.data.edit_bones.active=b
before=[(item.name,item.data.edit_bones.active.name,{b.name:(b.select,b.select_head,b.select_tail) for b in item.data.edit_bones}) for item in (obj,other)]
a.create_switch(bpy.context)
assert obj.mode==other.mode=="EDIT"
for item,label,states in [(obj,before[0][1],before[0][2]),(other,before[1][1],before[1][2])]:
    assert item.data.edit_bones.active.name==label
    assert all((item.data.edit_bones[n].select,item.data.edit_bones[n].select_head,item.data.edit_bones[n].select_tail)==state for n,state in states.items())
a.create_chains(bpy.context)
a.create_controls(bpy.context)
a.connect_ik(bpy.context)
a.match_rest_bend(bpy.context)
assert obj.mode==other.mode=="EDIT"
CASES.append("Multi-armature Edit Mode preserves mode, active bones, head-only selection and other rig")

# Two instances on one armature, shared Properties, no side-name guesses for roles.
bpy.ops.object.mode_set(mode="OBJECT")
other.select_set(False)
obj.select_set(True)
bpy.context.view_layer.objects.active=obj
bpy.ops.object.mode_set(mode="POSE")
a.connect_switch(bpy.context)
first_id=s.active_id
a.new_mapping(bpy.context)
with edit_active_armature(bpy.context,obj) as edits:
    names2={}
    for field in a.INPUTS:
        name=field+".R"
        bone=edits.new(name)
        index=a.ROLES.index(field.split("_",1)[1]) if field.startswith(("source_","tweak_")) else 3
        bone.head,bone.tail=(4,index,0),(4,index+1,0)
        names2[field]=name
for field,name in names2.items():
    setattr(s,field,name)
s.pole_direction_mode="EXPLICIT"
s.pole_direction=(1,0,0)
a.create_switch(bpy.context)
a.create_chains(bpy.context)
a.create_controls(bpy.context)
a.connect_ik(bpy.context)
s.property_mode="NEW"
a.connect_switch(bpy.context)
assert len(a.read_records(obj.data)["arms"])==2
assert len(obj.animation_data.drivers)==6
s.instance=next(item.name for item in s.instances if item.uid==first_id)
a.load_instance(bpy.context)
assert s.active_id==first_id
CASES.append("Multiple Arm instances per armature, per-side shared-property links, stable instance selection")

OZO_Tools.unregister()
report={"status":"PASS","blender":bpy.app.version_string,"cases":CASES}
(ROOT/"outputs"/"arm_edgecases_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print("OZO_ARM_EDGECASES_PASS",json.dumps(report,ensure_ascii=False))
