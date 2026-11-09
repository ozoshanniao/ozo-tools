# SPDX-License-Identifier: GPL-3.0-or-later
"""Build independent Tweak controls, then an FK chain from saved ORG rest data."""

import json
import math
import re
import uuid

import bpy
from bpy.props import BoolProperty, FloatProperty, PointerProperty, StringProperty
from mathutils import Matrix, Vector

from .bone_parenting import edit_active_armature

RECORD_KEY = "ozo_control_chains"
ID_KEY = "ozo_control_bone_id"
TOLERANCE = 1e-5


def base_name(name):
    name = name.strip()
    # Selection defines the sources. An existing ORG marker is only a naming
    # convention, never a filter or a requirement for the operation.
    for prefix in ("ORG_", "ORG-"):
        if name.startswith(prefix):
            name = name[len(prefix):].strip()
            break
    # Blender may put duplicate numbers before or after a side suffix.
    name = re.sub(r"(?:\.\d{3,})+$", "", name)
    side = name[-2:] if name.endswith((".L", ".R")) else ""
    stem = name[:-2] if side else name
    stem = re.sub(r"(?:\.\d{3,})+$", "", stem).strip()
    if not stem:
        raise ValueError("Removing the ORG prefix leaves an empty bone name")
    return stem, side


def read_records(armature):
    raw = armature.get(RECORD_KEY)
    if raw is None:
        return {"version": 1, "chains": []}
    try:
        records = json.loads(raw)
        if records["version"] != 1 or not isinstance(records["chains"], list):
            raise ValueError()
        for chain in records["chains"]:
            if not chain["entries"] or not isinstance(chain["entries"], list):
                raise ValueError()
            for entry in chain["entries"]:
                for key in ("source", "tweak", "fk", "name", "fk_name", "matrix", "length", "connected"):
                    if key not in entry:
                        raise ValueError()
            for key in ("tip", "tip_name", "parent", "complete"):
                if key not in chain:
                    raise ValueError()
        return records
    except (ValueError, TypeError, KeyError):
        raise ValueError("Invalid saved control-chain data") from None


def selected_names(context):
    if context.active_object.mode == "EDIT":
        return [b.name for b in (context.selected_editable_bones or [])
                if b.id_data == context.active_object.data]
    return [b.name for b in (context.selected_pose_bones_from_active_object or [])]


def destination(armature, enabled, name):
    collection = armature.collections_all.get(name) if enabled else armature.collections.active
    if collection is None:
        message = "Choose an existing bone collection" if enabled else "Set an active bone collection first"
        raise ValueError(message)
    if not collection.is_editable:
        raise ValueError(f"Bone collection is read-only: {collection.name}")
    return collection


def validate_names(armature, names):
    bones = armature.edit_bones if armature.is_editmode else armature.bones
    seen = set()
    for name in names:
        if len(name.encode("utf-8")) > 63:
            raise ValueError(f"Generated bone name exceeds Blender's limit: {name}")
        if name in seen or name in bones:
            raise ValueError(f"Bone name already exists or is generated twice: {name}")
        seen.add(name)
    # Old curves can address names that do not currently exist. New bones must
    # not accidentally acquire such animation or drivers, including in NLA.
    paths = tuple('pose.bones["' + bpy.utils.escape_identifier(n) + '"]' for n in names)
    for obj in bpy.data.objects:
        if obj.type != "ARMATURE" or obj.data != armature or not obj.animation_data:
            continue
        anim = obj.animation_data
        actions = {anim.action} if anim.action else set()
        def strip_actions(strips):
            for strip in strips:
                if strip.action:
                    actions.add(strip.action)
                if strip.type == "META":
                    strip_actions(strip.strips)
        for track in anim.nla_tracks:
            strip_actions(track.strips)
        curves = list(anim.drivers)
        for action in actions:
            for layer in action.layers:
                for strip in layer.strips:
                    if hasattr(strip, "channelbags"):
                        for bag in strip.channelbags:
                            curves.extend(bag.fcurves)
        for curve in curves:
            if any(curve.data_path == path or curve.data_path.startswith(path + ".")
                   or curve.data_path.startswith(path + "[") for path in paths):
                raise ValueError(f"Existing animation or driver addresses a new control: {curve.data_path}")


def geometry(bone, editing):
    matrix = bone.matrix if editing else bone.matrix_local
    return {"matrix": [list(row) for row in matrix], "length": bone.length}


def tweak_plan(context, settings):
    obj = context.active_object
    armature = obj.data
    names = selected_names(context)
    if not names:
        raise ValueError("Select ORG bones in Edit or Pose Mode")
    if not math.isfinite(settings.tweak_length) or settings.tweak_length <= 0:
        raise ValueError("Tweak length must be positive")
    collection = destination(armature, settings.tweak_use_collection, settings.tweak_collection)
    records = read_records(armature)
    editing = obj.mode == "EDIT"
    bones = armature.edit_bones if editing else armature.bones
    selected = set(names)
    children = {name: [] for name in names}
    for name in names:
        bone = bones[name]
        base_name(name)
        if bone.get(ID_KEY):
            raise ValueError(f"Bone already belongs to an OZO control chain: {name}")
        pose = obj.pose.bones.get(name)
        if pose and any(c.type == "STRETCH_TO" for c in pose.constraints):
            raise ValueError(f"ORG already has a Stretch To constraint: {name}")
        if bone.length <= TOLERANCE:
            raise ValueError(f"Bone is too short: {name}")
        parent = bone.parent
        if parent and parent.name in selected:
            children[parent.name].append(name)
            head = bone.head if editing else bone.head_local
            tail = parent.tail if editing else parent.tail_local
            if (head - tail).length > TOLERANCE:
                raise ValueError(f"ORG chain must meet head-to-tail: {parent.name} / {name}")
        else:
            ancestor = parent
            while ancestor:
                if ancestor.name in selected:
                    raise ValueError(f"Selection has a gap before: {name}")
                ancestor = ancestor.parent
    for name, descendants in children.items():
        if len(descendants) > 1:
            raise ValueError(f"Select unbranched chains; branching bone: {name}")
    chains, output_names = [], []
    roots = sorted(n for n in names if not bones[n].parent or bones[n].parent.name not in selected)
    for root in roots:
        bone = bones[root]
        chain = {"entries": [], "parent": bone.parent.name if bone.parent else None,
                 "tip": uuid.uuid4().hex, "complete": False}
        name = root
        while name is not None:
            bone = bones[name]
            stem, side = base_name(name)
            entry = {"source": uuid.uuid4().hex, "tweak": uuid.uuid4().hex,
                     "fk": uuid.uuid4().hex, "name": name,
                     "fk_name": stem + side, "tweak_name": stem + "_Tweak" + side,
                     "connected": bool(bone.use_connect), **geometry(bone, editing)}
            chain["entries"].append(entry)
            output_names.append(entry["tweak_name"])
            name = children[name][0] if children[name] else None
        chain["tip_name"] = stem + "_Tip_Tweak" + side
        output_names.append(chain["tip_name"])
        chains.append(chain)
    validate_names(armature, output_names)
    return records, chains, collection


def fk_plan(context, settings):
    armature = context.active_object.data
    records = read_records(armature)
    names = selected_names(context)
    if not names:
        raise ValueError("Select ORG or Tweak bones from a generated chain")
    # In Edit Mode the current identities live on EditBones, not cached Bones.
    bones = armature.edit_bones if context.active_object.mode == "EDIT" else armature.bones
    identities = {bones[name].get(ID_KEY) for name in names}
    chains, matched = [], set()
    for chain in records["chains"]:
        members = {chain["tip"]} | {e[k] for e in chain["entries"] for k in ("source", "tweak", "fk")}
        if identities & members:
            chains.append(chain)
            matched.update(members)
    if not chains or None in identities or identities - matched:
        raise ValueError("Select only bones belonging to generated OZO chains")
    collection = destination(armature, settings.fk_use_collection, settings.fk_collection)
    index = {}
    for bone in bones:
        identity = bone.get(ID_KEY)
        if identity:
            if identity in index:
                raise ValueError(f"Duplicated Tweak/FK identity: {index[identity]}, {bone.name}; use RIG Tools > Bone Identity > Repair Duplicate IDs")
            index[identity] = bone.name
    output_names = []
    for chain in chains:
        if chain["complete"]:
            raise ValueError("FK already exists for a selected chain")
        if chain["parent"] and chain["parent"] not in bones:
            raise ValueError(f"Original external parent is missing: {chain['parent']}")
        for identity in [chain["tip"]] + [e[k] for e in chain["entries"] for k in ("source", "tweak")]:
            if identity not in index:
                raise ValueError("A generated chain bone is missing; undo or restore it first")
        controls = [index[e["tweak"]] for e in chain["entries"]] + [index[chain["tip"]]]
        for name in controls:
            parent = bones[name].parent
            if (parent.name if parent else None) != chain["parent"]:
                raise ValueError(f"Tweak parent changed after creation: {name}")
        first = chain["entries"][0]
        if first["connected"] and chain["parent"]:
            parent = bones[chain["parent"]]
            tail = parent.tail if context.active_object.mode == "EDIT" else parent.tail_local
            if (Vector([first["matrix"][i][3] for i in range(3)]) - tail).length > TOLERANCE:
                raise ValueError("Original parent tail moved; cannot restore Connected without moving FK")
        for entry in chain["entries"]:
            source = bones[index[entry["source"]]]
            current = geometry(source, context.active_object.mode == "EDIT")
            if (abs(current["length"] - entry["length"]) > TOLERANCE or
                    max(abs(current["matrix"][i][j] - entry["matrix"][i][j])
                        for i in range(4) for j in range(4)) > TOLERANCE):
                raise ValueError(f"ORG rest geometry changed after creating Tweak: {source.name}")
            if not source.parent or source.parent.name != index[entry["tweak"]]:
                raise ValueError(f"ORG parent changed after creating Tweak: {source.name}")
            output_names.append(entry["fk_name"])
    validate_names(armature, output_names)
    return records, chains, collection, index


def make_control(bones, name, entry, identity, collection, length=None, tip=False):
    bone = bones.new(name)
    if bone.name != name:
        raise ValueError(f"Could not create exact bone name: {name}")
    matrix = Matrix(entry["matrix"])
    if tip:
        matrix.translation += matrix.to_3x3().col[1] * entry["length"]
    control_length = entry["length"] if length is None else length
    # A newly allocated EditBone has zero length: give it a valid axis before
    # setting its matrix, otherwise Blender cannot recover the intended roll.
    bone.head = matrix.translation
    bone.tail = matrix.translation + matrix.to_3x3().col[1] * control_length
    bone.matrix = matrix
    bone.length = control_length
    bone.use_deform = False
    bone.use_connect = False
    bone[ID_KEY] = identity
    bone.select = bone.select_head = bone.select_tail = False
    for existing in list(bone.collections):
        existing.unassign(bone)
    collection.assign(bone)
    return bone


def apply_plan(context, records, chains, collection, stage, length=None, index=None):
    """Rollback hierarchy, geometry, IDs, constraints and records on any failure."""
    obj = context.active_object
    armature = obj.data
    raw = armature.get(RECORD_KEY)
    created_constraints, created_bones, original = [], [], {}
    with edit_active_armature(context, obj) as bones:
        for bone in bones:
            original[bone.name] = {
                "parent": bone.parent.name if bone.parent else None,
                "connected": bone.use_connect, "head": bone.head.copy(),
                "tail": bone.tail.copy(), "roll": bone.roll, "id": bone.get(ID_KEY),
            }
    try:
        with edit_active_armature(context, obj) as bones:
            for chain in chains:
                parent = bones.get(chain["parent"]) if chain["parent"] else None
                for entry in chain["entries"]:
                    if stage == "TWEAK":
                        name = entry["tweak_name"]
                        created_bones.append(name)
                        control = make_control(bones, name, entry, entry["tweak"], collection, length)
                        control.parent = parent
                        source = bones[entry["name"]]
                        source.use_connect = False
                        source.parent = control
                        source[ID_KEY] = entry["source"]
                    else:
                        name = entry["fk_name"]
                        created_bones.append(name)
                        control = make_control(bones, name, entry, entry["fk"], collection)
                        control.parent = parent
                        control.use_connect = entry["connected"]
                        tweak = bones[index[entry["tweak"]]]
                        tweak.use_connect = False
                        tweak.parent = control
                        parent = control
                if stage == "TWEAK":
                    created_bones.append(chain["tip_name"])
                    tip = make_control(bones, chain["tip_name"], entry, chain["tip"], collection, length, tip=True)
                    tip.parent = parent
                else:
                    tip = bones[index[chain["tip"]]]
                    tip.use_connect = False
                    tip.parent = parent
                    chain["complete"] = True
        if stage == "TWEAK":
            # Pose constraints must be created after Edit Mode has synchronized.
            original_mode = obj.mode
            if original_mode == "EDIT":
                bpy.ops.object.mode_set(mode="OBJECT")
            try:
                for chain in chains:
                    entries = chain["entries"]
                    for i, entry in enumerate(entries):
                        pose = obj.pose.bones[entry["name"]]
                        constraint = pose.constraints.new("STRETCH_TO")
                        created_constraints.append((pose.name, constraint.name))
                        constraint.target = obj
                        constraint.subtarget = entries[i + 1]["tweak_name"] if i + 1 < len(entries) else chain["tip_name"]
                        # Initialize the rest length from rest geometry, not an
                        # arbitrary current pose. All other parameters are native defaults.
                        constraint.rest_length = entry["length"]
                records["chains"].extend(chains)
            finally:
                if original_mode == "EDIT":
                    bpy.ops.object.mode_set(mode="EDIT")
        armature[RECORD_KEY] = json.dumps(records)
        context.view_layer.update()
    except Exception:
        original_mode = obj.mode
        if original_mode == "EDIT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for name, constraint_name in created_constraints:
            constraint = obj.pose.bones[name].constraints.get(constraint_name)
            if constraint:
                obj.pose.bones[name].constraints.remove(constraint)
        if original_mode == "EDIT":
            bpy.ops.object.mode_set(mode="EDIT")
        with edit_active_armature(context, obj) as bones:
            for bone in bones:
                bone.use_connect = False
            for name, state in original.items():
                bones[name].parent = bones.get(state["parent"]) if state["parent"] else None
            for name in reversed(created_bones):
                if name in bones:
                    bones.remove(bones[name])
            for name, state in original.items():
                bone = bones[name]
                bone.head, bone.tail, bone.roll = state["head"], state["tail"], state["roll"]
                bone.use_connect = state["connected"]
                if state["id"] is None:
                    if ID_KEY in bone:
                        del bone[ID_KEY]
                else:
                    bone[ID_KEY] = state["id"]
        if raw is None:
            if RECORD_KEY in armature:
                del armature[RECORD_KEY]
        else:
            armature[RECORD_KEY] = raw
        raise
    return len(created_bones)


def create_tweak(context):
    settings = context.active_object.data.ozo_bone_controls
    records, chains, collection = tweak_plan(context, settings)
    return apply_plan(context, records, chains, collection, "TWEAK", settings.tweak_length)


def create_fk(context):
    settings = context.active_object.data.ozo_bone_controls
    records, chains, collection, index = fk_plan(context, settings)
    return apply_plan(context, records, chains, collection, "FK", index=index)


class OZO_PG_bone_controls(bpy.types.PropertyGroup):
    tweak_length: FloatProperty(name="Tweak Length", default=0.3, min=0.00001,
                               soft_max=2.0, precision=4, subtype="DISTANCE", unit="LENGTH",
                               description="Exact length in armature space; head stays fixed, also used for Tip")
    tweak_use_collection: BoolProperty(name="Specify Tweak Collection", default=False)
    tweak_collection: StringProperty(name="Tweak Collection", description="Existing bone collection")
    fk_use_collection: BoolProperty(name="Specify FK Collection", default=False)
    fk_collection: StringProperty(name="FK Collection", description="Existing bone collection")
    last_status: StringProperty(options={"SKIP_SAVE"})


class ControlsOperator:
    bl_translation_context = "OZO_Tools"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "ARMATURE" or obj.mode not in {"EDIT", "POSE"}:
            cls.poll_message_set("Select bones in Armature Edit or Pose Mode")
            return False
        if not obj.is_editable or not obj.data.is_editable or obj.override_library or obj.data.override_library:
            cls.poll_message_set("Use a local editable armature")
            return False
        if obj.data.users > 1:
            cls.poll_message_set("Make the armature data single-user first")
            return False
        return True

    def execute(self, context):
        try:
            count = self.run(context)
        except (ValueError, RuntimeError, TypeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        message = f"Created {count} {self.kind} bones"
        context.active_object.data.ozo_bone_controls.last_status = message
        self.report({"INFO"}, message)
        return {"FINISHED"}


class OZO_OT_create_tweak(ControlsOperator, bpy.types.Operator):
    bl_idname = "ozo.create_tweak"
    bl_label = "Create Tweak"
    bl_description = "Create Tweak and Tip controls for selected unbranched ORG chains, with Stretch To constraints"
    kind = "Tweak"
    run = staticmethod(create_tweak)


class OZO_OT_create_fk(ControlsOperator, bpy.types.Operator):
    bl_idname = "ozo.create_fk"
    bl_label = "Create FK"
    bl_description = "Create clean FK bones for whole generated chains containing selected ORG or Tweak bones"
    kind = "FK"
    run = staticmethod(create_fk)


class OZO_PT_bone_controls(bpy.types.Panel):
    bl_idname = "OZO_PT_bone_controls"
    bl_label = "RIG Tools"
    bl_translation_context = "OZO_Tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OZO_Tools"
    bl_order = 4

    def draw(self, context):
        pass


class OZO_PT_tweak_fk(bpy.types.Panel):
    bl_idname = "OZO_PT_tweak_fk"
    bl_label = "Tweak / FK"
    bl_translation_context = "OZO_Tools"
    bl_parent_id = "OZO_PT_bone_controls"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OZO_Tools"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 0

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
        settings = obj.data.ozo_bone_controls
        layout.label(text=f"Selected: {len(selected_names(context))} bones", translate=False)
        box = layout.box()
        box.prop(settings, "tweak_length", text="Tweak Length", translate=False)
        for kind, column in (("tweak", box), ("fk", layout.box())):
            label = "Tweak" if kind == "tweak" else "FK"
            column.prop(settings, kind + "_use_collection", text="Specify Collection", translate=False)
            if getattr(settings, kind + "_use_collection"):
                column.prop_search(settings, kind + "_collection", obj.data, "collections_all", text="Collection", translate=False)
            else:
                active = obj.data.collections.active
                column.label(text="Active: " + (active.name if active else "None"), translate=False)
            column.operator("ozo.create_" + kind, text="Create " + label, translate=False)
        if settings.last_status:
            layout.label(text=settings.last_status, translate=False)


CLASSES = (OZO_PG_bone_controls, OZO_OT_create_tweak, OZO_OT_create_fk,
           OZO_PT_bone_controls, OZO_PT_tweak_fk)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Armature.ozo_bone_controls = PointerProperty(type=OZO_PG_bone_controls)


def unregister():
    del bpy.types.Armature.ozo_bone_controls
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
