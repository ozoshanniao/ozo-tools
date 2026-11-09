# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicitly detach copied/unbound bone identities without deleting rig data."""
import json

import bpy
from bpy.props import BoolProperty, PointerProperty, StringProperty

from . import arm, rotation_follow as follow, rig_common as rig
from .bone_controls import selected_names
from . import identity_repair as repair


def require_rig(context):
    obj = context.active_object
    if not obj or obj.type != "ARMATURE" or obj.mode not in {"EDIT", "POSE"}:
        raise ValueError("Select copied/new controller bones in Edit or Pose Mode")
    if (not obj.is_editable or not obj.data.is_editable or obj.library or obj.data.library
            or obj.override_library or obj.data.override_library or obj.data.users != 1):
        raise ValueError("Use a local editable single-user armature")
    return obj


def contains(value, identity):
    if isinstance(value, dict):
        return identity in value or any(contains(v, identity) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains(v, identity) for v in value)
    return value == identity


def unique_index(groups, excluded):
    index = {}
    for uid, bones in groups.items():
        remaining = [b for b in bones if b.name not in excluded]
        if len(remaining) == 1:
            index[uid] = remaining[0]
    return index


def check_parent(child, expected, label):
    if child and expected and child.parent != expected:
        raise ValueError(f"Cannot retain identity on {expected.name}: existing {label} parent still points elsewhere; choose the actual original bone")


def check_property_driver(obj, constraint, retained, property_name):
    if not constraint:
        return
    curve = rig.driver_for(obj, constraint.path_from_id("influence"))
    if curve:
        expected = follow.property_path(obj.pose.bones[retained.name], property_name)
        targets = [t for v in curve.driver.variables if v.type == "SINGLE_PROP" for t in v.targets]
        if not any(t.id == obj and t.data_path == expected for t in targets):
            raise ValueError(f"Existing property driver does not reference retained original {retained.name}; no identity was cleared")


def verify_follow_references(obj, records, uid, retained, index):
    for record in records["bindings"].values():
        if not contains(record, uid):
            continue
        controlled = index.get(record["controlled"])
        mch = index.get(record["mch"]) if record["mch"] else None
        owner = mch if record["mode"] == "MCH" else controlled
        constraint = obj.pose.bones[owner.name].constraints.get(record["constraint"]) if owner and record["constraint"] else None
        if record["mode"] == "MCH":
            if record["controlled"] == uid and not rig.same_geometry(retained, record["geometry"]):
                raise ValueError(f"Retained original {retained.name} differs from the recorded controlled rest geometry")
            if uid in (record["controlled"], record["mch"]):
                check_parent(controlled, mch, "Rotation Follow controller")
            if record["parent"] == uid:
                check_parent(mch or controlled, retained, "Rotation Follow")
        if record["source"] == uid and constraint:
            if constraint.target != obj or constraint.subtarget != retained.name:
                raise ValueError(f"Existing Rotation Follow source does not point to retained original {retained.name}; select the copied bone instead")
        if record["link"] and record["link"]["bone"] == uid:
            check_property_driver(obj, constraint, retained, record["link"]["name"])


def verify_arm_references(obj, records, uid, retained, index):
    for record in records["arms"].values():
        if not contains(record, uid):
            continue
        mapping = {**record["mapping"], **record["bones"]}
        bones = {key: index.get(value) for key, value in mapping.items()}
        for role in arm.ROLES:
            if record["mapping"]["source_" + role] == uid and not rig.same_geometry(retained, record["sources"][role]):
                raise ValueError(f"Retained original {retained.name} differs from the recorded Arm source rest geometry")
        for group, step in (("switch", 0), ("fk", 1), ("ik", 1)):
            if not record["steps"][step]:
                continue
            for previous, current in zip(arm.ROLES, arm.ROLES[1:]):
                parent_key, child_key = group + "_" + previous, group + "_" + current
                if uid in (mapping[parent_key], mapping[child_key]):
                    check_parent(bones.get(child_key), bones.get(parent_key), "Arm chain")
        for key in ("tweak_arm", "tweak_forearm", "tweak_hand", "tip"):
            parent_key = "switch_" + (key[6:] if key.startswith("tweak_") else "hand")
            if uid in (mapping[key], mapping[parent_key]):
                check_parent(bones.get(key), bones.get(parent_key), "Arm Tweak")
        for saved in record["constraints"]:
            owner = bones.get(saved["owner"])
            constraint = obj.pose.bones[owner.name].constraints.get(saved["name"]) if owner else None
            if not constraint:
                continue
            for field, role in saved["targets"].items():
                if mapping[role] == uid and getattr(constraint, field) != retained.name:
                    raise ValueError(f"Arm constraint {saved['name']} does not target retained original {retained.name}")
            if record["link"] and record["link"]["bone"] == uid and saved.get("driven"):
                check_property_driver(obj, constraint, retained, record["link"]["name"])


def plan_clear(obj, names):
    if not names:
        raise ValueError("Select the copied/new controller bones whose identity should be cleared")
    data = obj.data
    selected = set(names)
    groups = {}
    for bone in data.bones:
        if bone.get(rig.BONE_ID):
            groups.setdefault(bone[rig.BONE_ID], []).append(bone)
    rf_records, arm_records = follow.read_records(data), arm.read_records(data)
    remove = [data.bones[name] for name in names if data.bones[name].get(rig.BONE_ID)]
    excluded = {b.name for b in remove}
    projected = unique_index(groups, excluded)
    original_name = data.ozo_bone_identity.original_bone
    retained_names = []
    checked = set()
    for bone in remove:
        uid = bone[rig.BONE_ID]
        if uid in checked:
            continue
        checked.add(uid)
        # Do not discard identities belonging to another tool or unknown record schema.
        for key in data.keys():
            raw = data.get(key)
            if (key.startswith("ozo_") and key not in {follow.RECORD_KEY, arm.RECORD_KEY}
                    and isinstance(raw, str) and uid in raw):
                raise ValueError(f"Identity is referenced by {key}; this cleanup cannot change that mechanism")
        referenced = contains(rf_records, uid) or contains(arm_records, uid)
        if not referenced:
            continue
        remaining = [b for b in groups[uid] if b.name not in selected]
        if not remaining:
            raise ValueError(f"{bone.name} owns an existing mechanism identity. Select copies only and leave the original unselected")
        if len(remaining) != 1:
            raise ValueError(f"Several originals remain for {bone.name}: {', '.join(b.name for b in remaining)}; select all copies and leave one original")
        retained = remaining[0]
        if original_name != retained.name:
            raise ValueError(f"This copied identity is used by existing mechanisms. Choose Original Bone = {retained.name} to retain it; process different originals separately")
        verify_follow_references(obj, rf_records, uid, retained, projected)
        verify_arm_references(obj, arm_records, uid, retained, projected)
        retained_names.append(retained.name)
    return remove, groups, retained_names


def settings_snapshot(data):
    snapshots = []
    for attr in ("ozo_rotation_follow", "ozo_arm"):
        settings = getattr(data, attr, None)
        if settings is None:
            continue
        fields = []
        for prop in settings.bl_rna.properties:
            key = prop.identifier
            if key.endswith("_id"):
                field = key[:-3]
                if field in settings.bl_rna.properties and field + "_label" in settings.bl_rna.properties:
                    fields.append((field, getattr(settings, field), getattr(settings, key), getattr(settings, field + "_label")))
        rows = [(i.name, i.bone_id, i.chain, i.order, i.base) for i in settings.affected] if attr == "ozo_rotation_follow" else None
        snapshots.append((attr, fields, rows, settings.active_index if rows is not None else None))
    return snapshots


def restore_settings(data, snapshots):
    for attr, fields, rows, active in snapshots:
        settings = getattr(data, attr)
        for field, value, uid, label in fields:
            setattr(settings, field, value)
            setattr(settings, field + "_id", uid)
            setattr(settings, field + "_label", label)
        if rows is not None:
            settings.affected.clear()
            for name, uid, chain, order, base in rows:
                item = settings.affected.add()
                item.name, item.bone_id, item.chain, item.order, item.base = name, uid, chain, order, base
            settings.active_index = active


def clear_preview_references(data, snapshots, cleared, groups):
    names = set(cleared)
    missing = {uid for uid, bones in groups.items() if all(b.name in names for b in bones)}
    for attr, fields, rows, active in snapshots:
        settings = getattr(data, attr)
        for field, value, uid, label in fields:
            if value in names or uid in missing:
                if uid in missing:
                    matches = [name for name, old in cleared.items() if old == uid]
                    if len(matches) == 1:
                        setattr(settings, field, matches[0])
                setattr(settings, field + "_id", "")
                setattr(settings, field + "_label", "")
        if rows is not None:
            for i in reversed(range(len(settings.affected))):
                item = settings.affected[i]
                if item.bone_id in missing or item.name in names and cleared[item.name] == item.bone_id:
                    settings.affected.remove(i)
            settings.active_index = min(settings.active_index, max(0, len(settings.affected) - 1))


def clear_identity(bone):
    del bone[rig.BONE_ID]


def clear_selected(context):
    obj = require_rig(context)
    names = selected_names(context)
    with rig.object_context(context):
        remove, groups, retained = plan_clear(obj, names)
        snapshots = settings_snapshot(obj.data)
        cleared = {bone.name: bone[rig.BONE_ID] for bone in remove}
        try:
            with rig.RigTransaction(context, "ozo_identity_cleanup_transaction"):
                for bone in remove:
                    clear_identity(bone)
                clear_preview_references(obj.data, snapshots, cleared, groups)
        except Exception:
            restore_settings(obj.data, snapshots)
            raise
    return {"count": len(cleared), "skipped": len(names) - len(cleared),
            "details": "\n".join(["Cleared: " + name for name in cleared] + ["Retained original: " + name for name in retained])}


def repair_duplicates(context):
    obj = require_rig(context)
    names = selected_names(context)
    with rig.object_context(context):
        changes, details, conflicts = repair.plan(obj, obj.data.ozo_bone_identity.original_bone, names)
        snapshots = settings_snapshot(obj.data)
        common_changes = {name: old for key, name, old, _ in changes if key == rig.BONE_ID}
        groups = {uid: [obj.data.bones[n] for n in names]
                  for uid, names in repair.groups_for(obj.data, rig.BONE_ID).items()}
        try:
            repair.apply(obj, changes)
            clear_preview_references(obj.data, snapshots, common_changes, groups)
        except Exception:
            repair.restore(obj, changes)
            restore_settings(obj.data, snapshots)
            raise
    return {"count": len({name for _, name, _, _ in changes}), "markers": len(changes),
            "conflicts": len(conflicts), "details": "\n".join(details + ["Unresolved: " + c for c in conflicts])
            or "No duplicated identities found in either OZO identity system."}


class OZO_PG_bone_identity(bpy.types.PropertyGroup):
    show_manual: BoolProperty(name="Manual / Advanced", default=False)
    original_bone: StringProperty(name="Original Bone", description="For bound copies, explicitly choose the unselected original that keeps the existing identity; optional for unbound bones")
    last_status: StringProperty(options={"SKIP_SAVE"})
    last_details: StringProperty(options={"SKIP_SAVE"})


class OZO_OT_repair_bone_identity(bpy.types.Operator):
    bl_idname = "ozo.repair_duplicate_bone_identities"
    bl_label = "Repair Duplicate IDs"
    bl_description = "Repair duplicated rig and Tweak/FK IDs on the active armature using recorded links; preserve original bindings and re-key copies"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return OZO_OT_clear_bone_identity.poll(context)

    def execute(self, context):
        settings = context.active_object.data.ozo_bone_identity
        try:
            result = repair_duplicates(context)
        except (ValueError, RuntimeError, TypeError) as error:
            settings.last_status, settings.last_details = "Repaired: 0 | Error", str(error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        settings.last_status = f"Repaired: {result['count']} | Unresolved: {result['conflicts']}"
        settings.last_details = result["details"]
        print("[OZO Identity Repair]", settings.last_status, result["details"], sep="\n")
        self.report({"WARNING"} if result["conflicts"] else {"INFO"}, settings.last_status)
        return {"FINISHED"}


class OZO_OT_identity_details(bpy.types.Operator):
    bl_idname = "ozo.bone_identity_details"
    bl_label = "Bone Identity Details"

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=640)

    def draw(self, context):
        import textwrap
        details = context.active_object.data.ozo_bone_identity.last_details
        for line in details.splitlines():
            for part in textwrap.wrap(line, width=88) or [""]:
                self.layout.label(text=part, translate=False)

    def execute(self, context):
        return {"FINISHED"}


class OZO_OT_clear_bone_identity(bpy.types.Operator):
    bl_idname = "ozo.clear_selected_bone_identity"
    bl_label = "Clear Selected Identity"
    bl_description = "Clear only OZO rig identity on selected copied/unbound bones; keep mechanisms, constraints and all other custom properties. Load Selected again afterward"
    bl_options = {"REGISTER", "UNDO"}
    bl_translation_context = "OZO_Tools"

    @classmethod
    def poll(cls, context):
        try:
            require_rig(context)
        except ValueError as error:
            cls.poll_message_set(str(error))
            return False
        return True

    def execute(self, context):
        settings = context.active_object.data.ozo_bone_identity
        try:
            result = clear_selected(context)
        except (ValueError, RuntimeError, TypeError) as error:
            settings.last_status, settings.last_details = "Cleared: 0 | Conflict", str(error)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        settings.last_status = f"Cleared: {result['count']} | Skipped: {result['skipped']}"
        settings.last_details = result["details"]
        print("[OZO Bone Identity]", settings.last_status, result["details"], sep="\n")
        self.report({"INFO"}, settings.last_status)
        return {"FINISHED"}


class OZO_PT_bone_identity(bpy.types.Panel):
    bl_idname = "OZO_PT_bone_identity"
    bl_label = "Bone Identity"
    bl_parent_id = "OZO_PT_bone_controls"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OZO_Tools"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 20

    def draw(self, context):
        layout = self.layout
        layout.use_property_decorate = False
        obj = context.active_object
        if not obj or obj.type != "ARMATURE":
            layout.label(text="Select an armature.", translate=False)
            return
        settings = obj.data.ozo_bone_identity
        layout.label(text="Active armature: both ID systems", translate=False)
        layout.operator("ozo.repair_duplicate_bone_identities", icon="FILE_REFRESH", translate=False)
        layout.prop(settings, "show_manual", text="Manual / Advanced", translate=False)
        if settings.show_manual:
            box = layout.box()
            box.label(text="For unresolved copies: select copies only.", translate=False)
            box.label(text="Original Bone (leave unselected)", translate=False)
            box.prop_search(settings, "original_bone", obj.data, "bones", text="", translate=False)
            box.label(text="Then retry Repair Duplicate IDs.", translate=False)
            box.separator()
            box.label(text="Clear selected rig IDs only (advanced)", translate=False)
            box.operator("ozo.clear_selected_bone_identity", translate=False)
        if settings.last_status:
            layout.label(text=settings.last_status, translate=False)
            layout.operator("ozo.bone_identity_details", text="Details", icon="INFO", translate=False)


CLASSES = (OZO_PG_bone_identity, OZO_OT_clear_bone_identity, OZO_OT_repair_bone_identity,
           OZO_OT_identity_details, OZO_PT_bone_identity)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Armature.ozo_bone_identity = PointerProperty(type=OZO_PG_bone_identity)


def unregister():
    del bpy.types.Armature.ozo_bone_identity
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
