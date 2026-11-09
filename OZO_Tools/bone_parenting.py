# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit per-armature DEF hierarchy templates and reversible parenting."""

from contextlib import contextmanager
import json

import bpy
from bpy.props import PointerProperty, StringProperty

TEMPLATE_KEY = "ozo_def_parenting_template"


def def_bones(armature):
    return {bone.name: bone for bone in armature.bones if bone.name.startswith("DEF")}


def save_template(armature):
    if not armature.is_editable:
        raise ValueError("Armature data is read-only")
    bones = def_bones(armature)
    if not bones:
        raise ValueError("No case-sensitive DEF-prefixed bones found")
    entries = [
        {"bone": bone.name, "parent": bone.parent.name if bone.parent else None,
         "connected": bool(bone.use_connect)}
        for bone in bones.values()
    ]
    armature[TEMPLATE_KEY] = json.dumps({"version": 1, "bones": entries})
    return len(entries)


def read_template(armature):
    raw = armature.get(TEMPLATE_KEY)
    if not raw:
        raise ValueError("Save Template before switching parents")
    try:
        data = json.loads(raw)
        if data["version"] != 1 or not isinstance(data["bones"], list) or not data["bones"]:
            raise ValueError()
        relationships = {}
        for entry in data["bones"]:
            name, parent, connected = entry["bone"], entry["parent"], entry["connected"]
            if (not isinstance(name, str) or not name.startswith("DEF")
                    or name in relationships or not isinstance(connected, bool)
                    or not (parent is None or isinstance(parent, str))):
                raise ValueError()
            relationships[name] = (parent, connected)
        return relationships
    except (TypeError, KeyError, ValueError):
        raise ValueError("Invalid parenting template; save a valid original hierarchy again") from None


def validate_relationships(armature, relationships):
    parents = {bone.name: bone.parent.name if bone.parent else None for bone in armature.bones}
    for name, (parent, connected) in relationships.items():
        bone = armature.bones.get(name)
        if bone is None:
            raise ValueError(f"Template bone missing or renamed: {name}")
        if parent is not None and parent not in parents:
            raise ValueError(f"Parent missing or renamed: {parent}")
        if connected and parent is not None and (bone.head_local - armature.bones[parent].tail_local).length > 1e-5:
            raise ValueError(f"Cannot restore Connected without moving {name}; its head no longer meets the parent's tail")
        parents[name] = parent
    # Include non-DEF bones when checking for indirect cycles.
    finished = set()
    order = []
    for name in parents:
        chain = []
        visiting = set()
        while name is not None and name not in finished:
            if name in visiting:
                raise ValueError("Target hierarchy would create a parenting cycle")
            visiting.add(name)
            chain.append(name)
            name = parents[name]
        for name in reversed(chain):
            finished.add(name)
            order.append(name)
    return order


@contextmanager
def edit_active_armature(context, obj):
    """Keep other selected armatures out of multi-object Edit Mode."""
    original_mode = obj.mode
    selected = list(context.selected_objects)
    was_selected = obj.select_get()
    try:
        if original_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for other in selected:
            if other != obj:
                other.select_set(False)
        obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        yield obj.data.edit_bones
    finally:
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for other in selected:
            other.select_set(True)
        obj.select_set(was_selected)
        if original_mode != "OBJECT":
            bpy.ops.object.mode_set(mode=original_mode)


def apply_relationships(context, relationships):
    obj = context.active_object
    armature = obj.data
    if not armature.is_editable:
        raise ValueError("Armature data is read-only")
    order = validate_relationships(armature, relationships)
    changed = {
        name: relation for name, relation in relationships.items()
        if (armature.bones[name].parent.name if armature.bones[name].parent else None,
            armature.bones[name].use_connect) != relation
    }
    if not changed:
        return 0
    with edit_active_armature(context, obj) as bones:
        geometry = {b.name: (b.head.copy(), b.tail.copy(), b.roll) for b in bones}
        original = {b.name: (b.parent.name if b.parent else None, b.use_connect) for b in bones}

        def assign(changes, bone_order):
            # Disconnect before editing so rest positions and lengths stay fixed.
            for bone in bones:
                bone.use_connect = False
            for name in changes:
                bones[name].parent = None
            for name, (parent, _) in changes.items():
                bones[name].parent = bones.get(parent) if parent is not None else None
            for name in bone_order:
                bone = bones[name]
                bone.head, bone.tail, bone.roll = geometry[name]
            for name in bone_order:
                bones[name].use_connect = changes.get(name, original[name])[1]

        try:
            assign(changed, order)
        except Exception:
            # Original parent-first order is recovered from the original graph.
            rollback_order = []
            visited = set()
            for name in original:
                chain = []
                while name is not None and name not in visited:
                    visited.add(name)
                    chain.append(name)
                    name = original[name][0]
                rollback_order.extend(reversed(chain))
            assign(original, rollback_order)
            raise
    context.view_layer.update()
    return len(changed)


def validated_template(armature):
    relationships = read_template(armature)
    if set(relationships) != set(def_bones(armature)):
        raise ValueError("DEF bones were added, removed, or renamed; the saved template no longer matches")
    # Also check that original parents still exist before allowing a switch.
    for parent, _ in relationships.values():
        if parent is not None and parent not in armature.bones:
            raise ValueError(f"Template parent missing or renamed: {parent}")
    return relationships


def to_root(context, root_name):
    armature = context.active_object.data
    original = validated_template(armature)
    if root_name not in armature.bones:
        raise ValueError("Select an existing Root bone")
    if root_name.startswith("DEF"):
        raise ValueError("Root must not be one of the DEF bones being reparented")
    return apply_relationships(context, {name: (root_name, False) for name in original})


def restore_original(context):
    return apply_relationships(context, validated_template(context.active_object.data))


class OZO_PG_bone_parenting(bpy.types.PropertyGroup):
    root_bone: StringProperty(
        name="Root", default="ROOT_SEC", translation_context="OZO_Tools",
        description="Target parent for every DEF bone in this armature",
    )
    last_status: StringProperty(options={"SKIP_SAVE"})


class ParentingOperator:
    bl_translation_context = "OZO_Tools"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "ARMATURE":
            cls.poll_message_set("Select an armature")
            return False
        if obj.mode not in {"OBJECT", "POSE"} or context.mode == "EDIT_ARMATURE":
            cls.poll_message_set("Use Object or Pose Mode")
            return False
        if not obj.is_editable or not obj.data.is_editable:
            cls.poll_message_set("Armature is read-only")
            return False
        return True

    def execute(self, context):
        try:
            count = self.run(context)
        except (ValueError, RuntimeError, TypeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        message = self.result_message.format(count=count)
        context.active_object.data.ozo_bone_parenting.last_status = message
        self.report({"INFO"}, message)
        return {"FINISHED"}


class OZO_OT_save_parenting(ParentingOperator, bpy.types.Operator):
    bl_idname = "ozo.save_parenting_template"
    bl_label = "Save Template"
    bl_description = "Save current DEF parents and Connected states; replaces this armature's previous template"
    result_message = "Saved {count} DEF bones"

    def run(self, context):
        return save_template(context.active_object.data)


class OZO_OT_def_to_root(ParentingOperator, bpy.types.Operator):
    bl_idname = "ozo.def_to_root"
    bl_label = "DEF To ROOT"
    bl_description = "Parent every DEF bone to Root without changing or saving the original template"
    result_message = "Reparented {count} DEF bones"

    def run(self, context):
        return to_root(context, context.active_object.data.ozo_bone_parenting.root_bone)


class OZO_OT_restore_parenting(ParentingOperator, bpy.types.Operator):
    bl_idname = "ozo.restore_parenting"
    bl_label = "Restore Original"
    bl_description = "Restore DEF parents and Connected states from this armature's saved template"
    result_message = "Restored {count} DEF bones"

    def run(self, context):
        return restore_original(context)


class OZO_PT_bone_parenting(bpy.types.Panel):
    bl_idname = "OZO_PT_bone_parenting"
    bl_label = "DEF Parenting"
    bl_translation_context = "OZO_Tools"
    bl_parent_id = "OZO_PT_tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OZO_Tools"
    bl_order = 2

    def draw(self, context):
        outer = self.layout.row()
        spacer = outer.column()
        spacer.ui_units_x = 1.0
        spacer.label(text="")
        layout = outer.column()
        layout.use_property_decorate = False
        obj = context.active_object
        if obj is None or obj.type != "ARMATURE":
            layout.label(text="Select an armature.", translate=False)
            return
        settings = obj.data.ozo_bone_parenting
        try:
            count = len(read_template(obj.data))
            status = f"Template: {count} DEF bones"
        except ValueError:
            status = "Template: Not saved" if TEMPLATE_KEY not in obj.data else "Template: Invalid"
        layout.label(text=status, translate=False)
        layout.operator("ozo.save_parenting_template", text="Save Template", icon="FILE_TICK", translate=False)
        layout.prop_search(settings, "root_bone", obj.data, "bones", text="Root", translate=False)
        row = layout.row(align=True)
        row.operator("ozo.def_to_root", text="DEF To ROOT", translate=False)
        row.operator("ozo.restore_parenting", text="Restore Original", translate=False)
        if settings.last_status:
            layout.label(text=settings.last_status, translate=False)


CLASSES = (
    OZO_PG_bone_parenting, OZO_OT_save_parenting, OZO_OT_def_to_root,
    OZO_OT_restore_parenting, OZO_PT_bone_parenting,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Armature.ozo_bone_parenting = PointerProperty(type=OZO_PG_bone_parenting)


def unregister():
    del bpy.types.Armature.ozo_bone_parenting
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
