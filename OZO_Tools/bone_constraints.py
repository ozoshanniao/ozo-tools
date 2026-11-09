# SPDX-License-Identifier: GPL-3.0-or-later
"""Synchronize same-armature copy transforms with case-sensitive prefixes."""

from dataclasses import dataclass, field

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty, StringProperty

CONSTRAINT_NAME = "OZO Copy Transforms"
EXPECTED_SETTINGS = {
    "owner_space": "WORLD",
    "target_space": "WORLD",
    "mix_mode": "REPLACE",
    "influence": 1.0,
    "mute": False,
    "head_tail": 0.0,
    "use_bbone_shape": False,
    "remove_target_shear": False,
    "space_object": None,
    "space_subtarget": "",
}


def constraint_enum_items(property_name):
    """Use the complete option set from this Blender version."""
    return tuple(
        (item.identifier, item.name, item.description)
        for item in bpy.types.CopyTransformsConstraint.bl_rna.properties[property_name].enum_items
    )


TARGET_SPACES = constraint_enum_items("target_space")
OWNER_SPACES = constraint_enum_items("owner_space")
MIX_MODES = constraint_enum_items("mix_mode")


@dataclass
class SyncResult:
    armatures: int = 0
    matched: int = 0
    added: int = 0
    repaired: int = 0
    correct: int = 0
    duplicates_removed: int = 0
    missing: int = 0
    read_only: int = 0
    conflicts: int = 0
    errors: int = 0
    details: list = field(default_factory=list)

    def summary(self):
        return (
            f"Added {self.added} | Repaired {self.repaired} | Correct {self.correct} | "
            f"Duplicates removed {self.duplicates_removed} | Unmatched {self.missing} | "
            f"Read-only {self.read_only} | Conflicts {self.conflicts} | Errors {self.errors}"
        )


def validate_prefixes(prefix_a, prefix_b):
    if not prefix_a or not prefix_b:
        raise ValueError("A and B prefixes must not be empty")
    if prefix_a == prefix_b:
        raise ValueError("A and B prefixes must differ to avoid self-targeting")
    if prefix_a.startswith(prefix_b) or prefix_b.startswith(prefix_a):
        raise ValueError("A and B prefixes must not overlap at the start")


def is_managed(constraint):
    return constraint.name == CONSTRAINT_NAME or constraint.name.startswith(
        CONSTRAINT_NAME + "."
    )


def is_correct(constraint, armature, target_name, expected=None):
    expected = EXPECTED_SETTINGS if expected is None else expected
    return (
        constraint.target == armature
        and constraint.subtarget == target_name
        and all(getattr(constraint, key) == value for key, value in expected.items())
    )


def select_candidates(bone, armature, target_name, prefix_b):
    """Only consolidate constraints identified as part of the A/B relationship.

    A lone copy-transforms constraint is considered the existing relationship
    even if its object/bone target is wrong. With several unrelated constraints,
    require identifiable evidence rather than guessing which one to overwrite.
    """
    copies = [c for c in bone.constraints if c.type == "COPY_TRANSFORMS"]
    candidates = [
        c for c in copies
        if is_managed(c)
        or c.subtarget == target_name
        or c.subtarget.startswith(prefix_b)
        or c.target is None
        or (c.target.type == "ARMATURE" and c.subtarget
            and c.target.pose.bones.get(c.subtarget) is None)
    ]
    if not candidates and len(copies) == 1:
        candidates = copies
    return candidates, bool(copies and not candidates)


def animated_settings(armature, constraints):
    """An animation/driver would override a fixed repair on the next frame."""
    prefixes = tuple(c.path_from_id() + "." for c in constraints)
    if not prefixes:
        return False
    animation = armature.animation_data
    if animation is None:
        return False
    curves = list(animation.drivers)
    actions = []
    if animation.action:
        actions.append(animation.action)
    for track in animation.nla_tracks:
        for strip in track.strips:
            if strip.action:
                actions.append(strip.action)
    for action in actions:
        # Blender 5 uses layered actions; include every channel bag/slot.
        for layer in action.layers:
            for strip in layer.strips:
                if hasattr(strip, "channelbags"):
                    for bag in strip.channelbags:
                        curves.extend(bag.fcurves)
    settings = set(EXPECTED_SETTINGS) | {"target", "subtarget"}
    return any(
        curve.data_path.startswith(prefixes)
        and curve.data_path.rsplit(".", 1)[-1] in settings
        for curve in curves
    )


def synchronize(scene, prefix_a, prefix_b, options=None):
    validate_prefixes(prefix_a, prefix_b)
    expected = dict(EXPECTED_SETTINGS)
    if options is not None:
        for key in ("target_space", "owner_space", "mix_mode", "influence"):
            expected[key] = getattr(options, key)
        if "CUSTOM" in (options.target_space, options.owner_space):
            if options.space_object is None:
                raise ValueError("Select a Space Object when using Custom Space")
            expected["space_object"] = options.space_object
            expected["space_subtarget"] = options.space_subtarget
            if options.space_subtarget:
                if options.space_object.type != "ARMATURE" or options.space_subtarget not in options.space_object.data.bones:
                    raise ValueError("Select an existing bone on the Space Object")
    result = SyncResult()
    for armature in scene.objects:
        if armature.type != "ARMATURE":
            continue
        result.armatures += 1
        for bone in armature.pose.bones:
            if not bone.name.startswith(prefix_a):
                continue
            target_name = prefix_b + bone.name[len(prefix_a):]
            label = f"{armature.name} / {bone.name} -> {target_name}"
            if armature.pose.bones.get(target_name) is None:
                result.missing += 1
                result.details.append(f"Unmatched: {label}")
                continue
            result.matched += 1
            if not armature.is_editable:
                result.read_only += 1
                result.details.append(f"Read-only: {label}")
                continue
            candidates, ambiguous = select_candidates(bone, armature, target_name, prefix_b)
            if ambiguous or animated_settings(armature, candidates):
                result.conflicts += 1
                reason = "ambiguous constraints" if ambiguous else "animated or driven settings"
                result.details.append(f"Conflict ({reason}): {label}")
                continue
            created = None
            try:
                if not candidates:
                    constraint = bone.constraints.new("COPY_TRANSFORMS")
                    created = constraint
                    constraint.name = CONSTRAINT_NAME
                else:
                    constraint = next(
                        (c for c in candidates if is_correct(c, armature, target_name, expected)),
                        candidates[0],
                    )
                correct = is_correct(constraint, armature, target_name, expected)
                # Check override permissions before writing any settings.
                changes = {"target": armature, "subtarget": target_name, **expected}
                changes = {k: v for k, v in changes.items() if getattr(constraint, k) != v}
                if any(constraint.is_property_readonly(k) for k in changes):
                    raise RuntimeError("Constraint properties are read-only")
                for key, value in changes.items():
                    setattr(constraint, key, value)
                if created:
                    result.added += 1
                elif correct:
                    result.correct += 1
                else:
                    result.repaired += 1
                for duplicate in candidates:
                    if duplicate != constraint:
                        bone.constraints.remove(duplicate)
                        result.duplicates_removed += 1
            except (RuntimeError, TypeError, ValueError, AttributeError) as error:
                if created is not None:
                    bone.constraints.remove(created)
                result.errors += 1
                result.details.append(f"Error: {label}: {error}")
    return result


class OZO_PG_bone_constraints(bpy.types.PropertyGroup):
    prefix_a: StringProperty(
        name="A", default="DEF", translation_context="OZO_Tools",
        description="Prefix of constrained bones (case-sensitive)",
    )
    prefix_b: StringProperty(
        name="B", default="ORG", translation_context="OZO_Tools",
        description="Prefix of source bones; the remaining name must match exactly",
    )
    target_space: EnumProperty(name="Target Space", items=TARGET_SPACES, default="WORLD", translation_context="OZO_Tools")
    owner_space: EnumProperty(name="Owner Space", items=OWNER_SPACES, default="WORLD", translation_context="OZO_Tools")
    mix_mode: EnumProperty(name="Mix", items=MIX_MODES, default="REPLACE", translation_context="OZO_Tools")
    influence: FloatProperty(name="Influence", default=1.0, min=0.0, max=1.0, translation_context="OZO_Tools")
    space_object: PointerProperty(name="Space Object", type=bpy.types.Object, translation_context="OZO_Tools")
    space_subtarget: StringProperty(name="Space Bone", translation_context="OZO_Tools")
    show_options: BoolProperty(name="Options", default=False, options={"SKIP_SAVE"}, translation_context="OZO_Tools")
    last_result: StringProperty(options={"SKIP_SAVE"})
    last_details: StringProperty(options={"SKIP_SAVE"})
    last_status: StringProperty(options={"SKIP_SAVE"})


class OZO_OT_sync_bone_constraints(bpy.types.Operator):
    bl_idname = "ozo.sync_bone_constraints"
    bl_label = "Apply"
    bl_translation_context = "OZO_Tools"
    bl_description = "Add or repair Copy Transforms on A bones using matching B bones"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if context.mode == "EDIT_ARMATURE":
            cls.poll_message_set("Exit Armature Edit Mode first")
            return False
        return context.scene is not None

    def execute(self, context):
        settings = context.scene.ozo_bone_constraints
        try:
            result = synchronize(context.scene, settings.prefix_a, settings.prefix_b, settings)
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        settings.last_result = result.summary()
        settings.last_details = "\n".join(result.details)
        settings.last_status = f"Added {result.added} / Fixed {result.repaired}"
        context.view_layer.update()
        for detail in result.details:
            print(f"[OZO_Tools] {detail}")
        print(f"[OZO_Tools] {result.summary()}")
        warning = result.errors or result.conflicts or result.read_only or not result.matched
        self.report({"WARNING"} if warning else {"INFO"}, result.summary())
        return {"FINISHED"}


class OZO_OT_constraint_report(bpy.types.Operator):
    bl_idname = "ozo.constraint_report"
    bl_label = "Details"
    bl_translation_context = "OZO_Tools"
    bl_description = "View the last operation results"

    def execute(self, context):
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=600)

    def draw(self, context):
        settings = context.scene.ozo_bone_constraints
        for item in settings.last_result.split(" | "):
            self.layout.label(text=item, translate=False)
        lines = settings.last_details.splitlines()
        for line in lines[:25]:
            self.layout.label(text=line, translate=False)
        if len(lines) > 25:
            self.layout.label(text=f"{len(lines) - 25} more entries in the system console", translate=False)
        elif not lines:
            self.layout.label(text="No issues", translate=False)


class OZO_PT_tools(bpy.types.Panel):
    bl_idname = "OZO_PT_tools"
    bl_label = "OZO_Tools"
    bl_translation_context = "OZO_Tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OZO_Tools"

    def draw(self, context):
        pass


class OZO_PT_bone_constraints(bpy.types.Panel):
    bl_idname = "OZO_PT_bone_constraints"
    bl_label = "Copy Transform"
    bl_translation_context = "OZO_Tools"
    bl_parent_id = "OZO_PT_tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OZO_Tools"

    def draw(self, context):
        settings = context.scene.ozo_bone_constraints
        # Subpanel headers are indented by Blender; align their contents too.
        outer = self.layout.row()
        spacer = outer.column()
        spacer.ui_units_x = 1.0
        spacer.label(text="")
        layout = outer.column()
        layout.use_property_split = False
        layout.use_property_decorate = False
        column = layout.column(align=True)
        column.prop(settings, "prefix_a", text="A", translate=False)
        column.prop(settings, "prefix_b", text="B", translate=False)
        layout.label(text="A copies transforms from B.", translate=False)
        header = layout.row()
        header.alignment = "LEFT"
        header.prop(settings, "show_options", text="Options", translate=False,
                    icon="TRIA_DOWN" if settings.show_options else "TRIA_RIGHT",
                    emboss=False, toggle=True)
        if settings.show_options:
            body = layout.column()
            body.use_property_split = True
            body.prop(settings, "target_space", translate=False)
            body.prop(settings, "owner_space", translate=False)
            if "CUSTOM" in (settings.target_space, settings.owner_space):
                body.prop(settings, "space_object", translate=False)
                if settings.space_object is not None and settings.space_object.type == "ARMATURE":
                    body.prop_search(settings, "space_subtarget", settings.space_object.data, "bones", translate=False)
            body.prop(settings, "mix_mode", translate=False)
            body.prop(settings, "influence", slider=True, translate=False)
        layout.operator("ozo.sync_bone_constraints", text="Apply", icon="CONSTRAINT_BONE", translate=False)
        if settings.last_result:
            row = layout.row(align=True)
            row.label(text=settings.last_status, translate=False)
            row.operator("ozo.constraint_report", text="", icon="INFO")


CLASSES = (
    OZO_PG_bone_constraints, OZO_OT_sync_bone_constraints,
    OZO_OT_constraint_report, OZO_PT_tools, OZO_PT_bone_constraints,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ozo_bone_constraints = PointerProperty(type=OZO_PG_bone_constraints)


def unregister():
    del bpy.types.Scene.ozo_bone_constraints
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
