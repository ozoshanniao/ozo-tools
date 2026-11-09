"""Real Blender regression test for the Deform tool."""

from pathlib import Path
import sys
import tempfile

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import OZO_Tools
from OZO_Tools.bone_deform import fix_deform


def rig(name, names):
    obj = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for index, name in enumerate(names):
        bone = obj.data.edit_bones.new(name)
        bone.head = (index, 0, 0)
        bone.tail = (index, 0, 1)
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


scene = bpy.context.scene
deform_bones = ["DEF", "DEF-arm", "DEF_arm", "DEF-off", "ROOT", "ROOT.001", "ROOT-control"]
controls = ["ORG-arm", "MCH-arm", "root", "Root", "def-arm", "already-off"]
main = rig("Main", deform_bones + controls)
main.data.bones["DEF-off"].use_deform = False
main.data.bones["ROOT"].use_deform = False
main.data.bones["ROOT.001"].use_deform = False
main.data.bones["ROOT-control"].use_deform = False
main.data.bones["already-off"].use_deform = False
hidden = rig("Hidden", ["CTRL-hidden", "DEF-hidden"])
hidden.hide_set(True)
hidden.hide_viewport = True
shared = bpy.data.objects.new("Shared", main.data)
scene.collection.objects.link(shared)
outside = rig("Outside", ["CTRL-outside", "DEF-outside"])
outside.data.bones["DEF-outside"].use_deform = False
bpy.data.scenes.new("OtherScene").collection.objects.link(outside)
scene.collection.objects.unlink(outside)

with tempfile.TemporaryDirectory(prefix="deform_test_", dir=ROOT / "tests") as directory:
    source = rig("Linked", ["ORG-linked", "DEF-linked"])
    source.data.bones["DEF-linked"].use_deform = False
    library = Path(directory) / "readonly.blend"
    bpy.data.libraries.write(str(library), {source.data})
    bpy.data.objects.remove(source, do_unlink=True)
    with bpy.data.libraries.load(str(library), link=True) as (data_from, data_to):
        data_to.armatures = ["Linked"]
    linked = bpy.data.objects.new("LinkedObject", data_to.armatures[0])
    scene.collection.objects.link(linked)
    assert not linked.data.is_editable

    OZO_Tools.register()
    result = fix_deform(scene)
    assert result.enabled == 4, result
    assert result.disabled == 6, result
    assert result.correct == 5, result
    assert result.read_only == 2, result
    assert result.errors == 0, result
    assert all(not main.data.bones[name].use_deform for name in controls)
    assert all(main.data.bones[name].use_deform for name in deform_bones)
    assert not hidden.data.bones["CTRL-hidden"].use_deform
    assert hidden.data.bones["DEF-hidden"].use_deform
    assert outside.data.bones["CTRL-outside"].use_deform
    assert not outside.data.bones["DEF-outside"].use_deform
    assert linked.data.bones["ORG-linked"].use_deform
    assert not linked.data.bones["DEF-linked"].use_deform
    assert shared.data == main.data

    again = fix_deform(scene)
    assert again.enabled == again.disabled == 0 and again.correct == 15, again
    assert again.read_only == 2, again
    bpy.context.view_layer.objects.active = None
    assert bpy.ops.ozo.fix_deform() == {"FINISHED"}
    assert "Disabled 0" in scene.ozo_bone_deform.last_status
    assert "Read-only" in scene.ozo_bone_deform.last_details
    assert "UNDO" in bpy.types.Operator.bl_rna_get_subclass_py("OZO_OT_fix_deform").bl_options
    bpy.context.view_layer.objects.active = main
    main.select_set(True)
    bpy.ops.object.mode_set(mode="POSE")
    assert bpy.ops.ozo.fix_deform.poll()
    bpy.ops.object.mode_set(mode="EDIT")
    assert not bpy.ops.ozo.fix_deform.poll()
    bpy.ops.object.mode_set(mode="OBJECT")
    OZO_Tools.unregister()
    assert not hasattr(bpy.types.Scene, "ozo_bone_deform")
    assert not hasattr(bpy.types.Scene, "ozo_bone_constraints")
    OZO_Tools.register()
    OZO_Tools.unregister()
    # Release linked data before the temporary library is cleaned up.
    linked_data = linked.data
    bpy.data.objects.remove(linked, do_unlink=True)
    bpy.data.armatures.remove(linked_data)

print("OZO_DEFORM_PASS", bpy.app.version_string, result.summary(), "repeat:", again.summary())
