"""Install the delivered ZIP in a temporary workspace repository only."""

from pathlib import Path
import tempfile
import tomllib

import bpy
import addon_utils

root = Path(__file__).resolve().parents[1]
version = tomllib.loads((root / "OZO_Tools" / "blender_manifest.toml").read_text("utf-8"))["version"]
bpy.context.preferences.use_preferences_save = False
with tempfile.TemporaryDirectory(prefix="ozo_install_", dir=root / "tests") as directory:
    repos = bpy.context.preferences.extensions.repos
    repo = repos.new(
        name="OZO ZIP Test", module="ozo_zip_test",
        custom_directory=directory, remote_url="", source="USER",
    )
    status = bpy.ops.extensions.package_install_files(
        filepath=str(root / "dist" / f"OZO_Tools-{version}.zip"),
        repo="ozo_zip_test", enable_on_install=True,
    )
    assert status == {"FINISHED"}, status
    module = "bl_ext.ozo_zip_test.ozo_tools"
    assert addon_utils.check(module)[1], "Installed extension was not enabled"
    assert hasattr(bpy.types.Scene, "ozo_bone_constraints")
    panel = bpy.types.Panel.bl_rna_get_subclass_py("OZO_PT_bone_constraints")
    assert panel.bl_space_type == "VIEW_3D"
    assert panel.bl_region_type == "UI"
    assert panel.bl_category == "OZO_Tools"
    assert panel.bl_label == "Copy Transform"
    assert panel.bl_parent_id == "OZO_PT_tools"
    parent = bpy.types.Panel.bl_rna_get_subclass_py("OZO_PT_tools")
    assert parent.bl_label == "OZO_Tools"
    deform = bpy.types.Panel.bl_rna_get_subclass_py("OZO_PT_bone_deform")
    assert deform.bl_parent_id == panel.bl_parent_id
    assert deform.bl_label == "Deform"
    assert hasattr(bpy.types.Scene, "ozo_bone_deform")
    assert bpy.ops.ozo.fix_deform() == {"FINISHED"}
    parenting = bpy.types.Panel.bl_rna_get_subclass_py("OZO_PT_bone_parenting")
    assert parenting.bl_parent_id == panel.bl_parent_id
    assert parenting.bl_label == "DEF Parenting"
    assert hasattr(bpy.types.Armature, "ozo_bone_parenting")
    controls = bpy.types.Panel.bl_rna_get_subclass_py("OZO_PT_bone_controls")
    assert not getattr(controls, "bl_parent_id", "")
    assert controls.bl_label == "RIG Tools"
    assert controls.bl_category == panel.bl_category
    tweak_fk = bpy.types.Panel.bl_rna_get_subclass_py("OZO_PT_tweak_fk")
    socket = bpy.types.Panel.bl_rna_get_subclass_py("OZO_PT_bone_socket")
    assert tweak_fk.bl_parent_id == socket.bl_parent_id == controls.bl_idname
    assert hasattr(bpy.types.Armature, "ozo_bone_controls")
    assert hasattr(bpy.types.Armature, "ozo_bone_socket")
    follow = bpy.types.Panel.bl_rna_get_subclass_py("OZO_PT_rotation_follow")
    assert follow.bl_parent_id == controls.bl_idname
    assert follow.bl_label == "Rotation Follow"
    assert hasattr(bpy.types.Armature, "ozo_rotation_follow")
    identity_panel = bpy.types.Panel.bl_rna_get_subclass_py("OZO_PT_bone_identity")
    assert identity_panel.bl_parent_id == controls.bl_idname
    assert hasattr(bpy.types.Armature, "ozo_bone_identity")
    assert not bpy.ops.ozo.clear_selected_bone_identity.poll()
    assert not bpy.ops.ozo.repair_duplicate_bone_identities.poll()
    assert bpy.ops.ozo.bone_identity_details.get_rna_type().name == "Bone Identity Details"
    arm = bpy.types.Panel.bl_rna_get_subclass_py("OZO_PT_arm")
    assert arm.bl_parent_id == controls.bl_idname and arm.bl_label == "Arm"
    assert hasattr(bpy.types.Armature, "ozo_arm")
    assert not bpy.ops.ozo.arm_switch.poll()
    assert not bpy.ops.ozo.follow_connect_rotation.poll()
    assert not bpy.ops.ozo.create_socket.poll()
    assert not bpy.ops.ozo.create_tweak.poll()
    assert not bpy.ops.ozo.create_fk.poll()
    assert not bpy.ops.ozo.save_parenting_template.poll()
    animation = bpy.types.Panel.bl_rna_get_subclass_py("OZO_PT_animation_scale")
    assert animation.bl_parent_id == panel.bl_parent_id
    assert animation.bl_label == "Animation Scale"
    assert hasattr(bpy.types.Scene, "ozo_animation_scale")
    assert not bpy.ops.ozo.normalize_animation_scale.poll()
    assert bpy.types.Panel.bl_rna_get_subclass_py("OZO_PT_animation_transfer") is None
    assert not hasattr(bpy.types.Scene, "ozo_animation_transfer")
    assert bpy.ops.ozo.sync_bone_constraints.poll()
    assert bpy.ops.ozo.sync_bone_constraints() == {"FINISHED"}
    addon_utils.disable(module, default_set=True)
    assert not hasattr(bpy.types.Scene, "ozo_bone_constraints")
    assert not hasattr(bpy.types.Scene, "ozo_bone_deform")
    assert not hasattr(bpy.types.Armature, "ozo_bone_parenting")
    assert not hasattr(bpy.types.Armature, "ozo_bone_controls")
    assert not hasattr(bpy.types.Armature, "ozo_bone_socket")
    assert not hasattr(bpy.types.Armature, "ozo_rotation_follow")
    assert not hasattr(bpy.types.Armature, "ozo_bone_identity")
    assert not hasattr(bpy.types.Armature, "ozo_arm")
    assert not hasattr(bpy.types.Scene, "ozo_animation_scale")
    assert not hasattr(bpy.types.Scene, "ozo_animation_transfer")
    repos.remove(repo)
print("OZO_ZIP_INSTALL_PASS: Blender", bpy.app.version_string)
