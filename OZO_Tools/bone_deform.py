# SPDX-License-Identifier: GPL-3.0-or-later
"""Enable deformation for DEF*/ROOT* bones and disable it for all others."""

from dataclasses import dataclass, field

import bpy
from bpy.props import PointerProperty, StringProperty


@dataclass
class DeformResult:
    enabled: int = 0
    disabled: int = 0
    correct: int = 0
    read_only: int = 0
    errors: int = 0
    details: list = field(default_factory=list)

    def summary(self):
        return (
            f"Enabled {self.enabled} | Disabled {self.disabled} | Correct {self.correct} | "
            f"Read-only {self.read_only} | Errors {self.errors}"
        )


def fix_deform(scene):
    result = DeformResult()
    seen = set()
    for obj in scene.objects:
        if obj.type != "ARMATURE":
            continue
        armature = obj.data
        identity = armature.as_pointer()
        if identity in seen:
            continue
        seen.add(identity)
        for bone in armature.bones:
            desired = bone.name.startswith(("DEF", "ROOT"))
            if bone.use_deform == desired:
                result.correct += 1
                continue
            label = f"{armature.name} / {bone.name}"
            if not armature.is_editable or bone.is_property_readonly("use_deform"):
                result.read_only += 1
                result.details.append(f"Read-only: {label}")
                continue
            try:
                bone.use_deform = desired
                if desired:
                    result.enabled += 1
                else:
                    result.disabled += 1
            except (RuntimeError, TypeError, ValueError) as error:
                result.errors += 1
                result.details.append(f"Error: {label}: {error}")
    return result


class OZO_PG_bone_deform(bpy.types.PropertyGroup):
    last_status: StringProperty(options={"SKIP_SAVE"})
    last_result: StringProperty(options={"SKIP_SAVE"})
    last_details: StringProperty(options={"SKIP_SAVE"})


class OZO_OT_fix_deform(bpy.types.Operator):
    bl_idname = "ozo.fix_deform"
    bl_label = "Fix Deform"
    bl_translation_context = "OZO_Tools"
    bl_description = (
        "Enable Deform for case-sensitive DEF or ROOT prefixes; "
        "disable Deform for all other scene bones"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if context.mode == "EDIT_ARMATURE":
            cls.poll_message_set("Exit Armature Edit Mode first")
            return False
        return context.scene is not None

    def execute(self, context):
        result = fix_deform(context.scene)
        settings = context.scene.ozo_bone_deform
        settings.last_status = f"Enabled {result.enabled} / Disabled {result.disabled}"
        settings.last_result = result.summary()
        settings.last_details = "\n".join(result.details)
        context.view_layer.update()
        for detail in result.details:
            print(f"[OZO_Tools] {detail}")
        print(f"[OZO_Tools] {result.summary()}")
        self.report({"WARNING"} if result.errors or result.read_only else {"INFO"}, result.summary())
        return {"FINISHED"}


class OZO_OT_deform_report(bpy.types.Operator):
    bl_idname = "ozo.deform_report"
    bl_label = "Deform Details"
    bl_translation_context = "OZO_Tools"
    bl_description = "View the last Deform operation results"

    def execute(self, context):
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=500)

    def draw(self, context):
        settings = context.scene.ozo_bone_deform
        for item in settings.last_result.split(" | "):
            self.layout.label(text=item, translate=False)
        lines = settings.last_details.splitlines()
        for line in lines[:25]:
            self.layout.label(text=line, translate=False)
        if len(lines) > 25:
            self.layout.label(text=f"{len(lines) - 25} more entries in the system console", translate=False)


class OZO_PT_bone_deform(bpy.types.Panel):
    bl_idname = "OZO_PT_bone_deform"
    bl_label = "Deform"
    bl_translation_context = "OZO_Tools"
    bl_parent_id = "OZO_PT_tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OZO_Tools"
    bl_order = 1

    def draw(self, context):
        outer = self.layout.row()
        spacer = outer.column()
        spacer.ui_units_x = 1.0
        spacer.label(text="")
        layout = outer.column()
        layout.use_property_decorate = False
        layout.label(text="Enable DEF* / ROOT* only.", translate=False)
        layout.operator("ozo.fix_deform", text="Fix Deform", icon="BONE_DATA", translate=False)
        settings = context.scene.ozo_bone_deform
        if settings.last_result:
            row = layout.row(align=True)
            row.label(text=settings.last_status, translate=False)
            row.operator("ozo.deform_report", text="", icon="INFO")


CLASSES = (OZO_PG_bone_deform, OZO_OT_fix_deform, OZO_OT_deform_report, OZO_PT_bone_deform)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ozo_bone_deform = PointerProperty(type=OZO_PG_bone_deform)


def unregister():
    del bpy.types.Scene.ozo_bone_deform
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
