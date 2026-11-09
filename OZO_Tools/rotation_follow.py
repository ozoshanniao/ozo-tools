# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit, staged rotation follow with persistent mappings and optional total control."""
import json
import math
import uuid

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)

from . import rig_common as rig
from .bone_controls import destination, selected_names, validate_names

RECORD_KEY = "ozo_rotation_follow_records"
OPTION_FIELDS = ("target_space", "owner_space", "mix_mode", "use_x", "use_y", "use_z",
                 "invert_x", "invert_y", "invert_z")
SIGNATURE_FIELDS = OPTION_FIELDS + ("mute", "euler_order", "use_offset")


def enum_items(name, exclude=()):
    return tuple((i.identifier, i.name, i.description) for i in
                 bpy.types.CopyRotationConstraint.bl_rna.properties[name].enum_items
                 if i.identifier not in exclude)


TARGET_SPACES = enum_items("target_space", {"CUSTOM"})
OWNER_SPACES = enum_items("owner_space", {"CUSTOM"})
MIX_MODES = enum_items("mix_mode")


def read_records(data):
    try:
        result = json.loads(data.get(RECORD_KEY, '{"version":1,"bindings":{}}'))
        if result["version"] != 1 or not isinstance(result["bindings"], dict):
            raise ValueError()
        for key, record in result["bindings"].items():
            if key != record["controlled"] or record["mode"] not in {"DIRECT", "MCH"}:
                raise ValueError()
            for field in ("id", "source", "mch", "constraint", "base", "link"):
                if field not in record:
                    raise ValueError()
        return result
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("Invalid Rotation Follow records; restore a valid saved mechanism") from None


def save_records(data, records):
    data[RECORD_KEY] = json.dumps(records, ensure_ascii=False)


def resolve_input(settings, field, index, data):
    name = getattr(settings, field)
    cached = getattr(settings, field + "_id")
    label = getattr(settings, field + "_label")
    if cached and name == label:
        return rig.resolve(index, cached, field.replace("_", " "))
    bone = data.bones.get(name)
    if not bone:
        raise ValueError(f"Choose an existing {field.replace('_', ' ')} on this armature")
    return bone


def remember_input(settings, field, bone):
    setattr(settings, field, bone.name)
    setattr(settings, field + "_label", bone.name)
    setattr(settings, field + "_id", rig.identity(bone))


def logical_parents(data, records, index):
    intermediates = {r["mch"] for r in records["bindings"].values() if r["mch"]}
    parents = {}
    for bone in data.bones:
        parent = bone.parent
        while parent and parent.get(rig.BONE_ID) in intermediates:
            parent = parent.parent
        parents[bone.name] = parent.name if parent else None
    return parents


def ordered_chains(names, parents):
    selected = set(names)
    if len(names) != len(selected):
        raise ValueError("Affected selection overlaps: select each controller only once")
    children = {name: [] for name in names}
    for name in names:
        parent = parents[name]
        if parent in selected:
            children[parent].append(name)
        else:
            ancestor = parent
            while ancestor:
                if ancestor in selected:
                    raise ValueError(f"Selection has an internal gap before {name}; select a continuous chain or process it separately")
                ancestor = parents[ancestor]
    for name, descendants in children.items():
        if len(descendants) > 1:
            raise ValueError(f"Selection branches at {name}; process the branches separately")
    chains = []
    for root in sorted(n for n in names if parents[n] not in selected):
        chain, current = [], root
        while current is not None:
            chain.append(current)
            current = children[current][0] if children[current] else None
        chains.append(chain)
    if sum(map(len, chains)) != len(names):
        raise ValueError("Cannot partition the selected hierarchy into unambiguous chains")
    return chains


def distribution(settings, names, parents):
    if not settings.auto_falloff:
        return [(name, i, 0, 1.0) for i, name in enumerate(sorted(names))]
    output = []
    for chain_index, chain in enumerate(ordered_chains(names, parents)):
        for order, name in enumerate(chain):
            t = order / (len(chain) - 1) if len(chain) > 1 else 0
            base = settings.start_influence + (settings.end_influence - settings.start_influence) * t
            output.append((name, chain_index, order, base))
    return output


def affected(settings, index):
    if not settings.affected:
        raise ValueError("Load Selected to fix the affected-bone list first")
    result, seen = [], set()
    for item in settings.affected:
        bone = rig.resolve(index, item.bone_id, f"affected bone {item.name}")
        if item.bone_id in seen:
            raise ValueError(f"Overlapping affected entry: {bone.name}")
        seen.add(item.bone_id)
        result.append((item, bone))
    return result


def effective_base(settings, item):
    value = float(item.base) if settings.auto_falloff else 1.0
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"Influence must be finite and within 0..1: {item.name}")
    return value


def validate_preview(settings, rows, records, data, index):
    if settings.auto_falloff:
        ordered_chains([b.name for _, b in rows], logical_parents(data, records, index))
    for item, _ in rows:
        effective_base(settings, item)


def load_selected(context):
    obj = rig.require_rig(context)
    names = selected_names(context)
    if not names:
        raise ValueError("Select affected bones on the active armature")
    with rig.object_context(context), rig.RigTransaction(context, RECORD_KEY):
        settings = obj.data.ozo_rotation_follow
        records, index = read_records(obj.data), rig.index_bones(obj.data)
        mch_to_controlled = {r["mch"]: r["controlled"] for r in records["bindings"].values() if r["mch"]}
        converted = []
        for name in names:
            bone = obj.data.bones[name]
            if bone.get(rig.BONE_ID) in mch_to_controlled:
                bone = rig.resolve(index, mch_to_controlled[bone[rig.BONE_ID]], "controlled bone")
            converted.append(bone.name)
        if len(set(converted)) != len(converted):
            raise ValueError("Overlapping selection: a controller and its MCH both refer to the same affected bone")
        source = resolve_input(settings, "rotation_source", index, obj.data)
        if source.name in converted:
            raise ValueError(f"Rotation Source cannot also be affected: {source.name}")
        rows = distribution(settings, converted, logical_parents(obj.data, records, index))
        rig.check_cycles(obj, source.name, converted)
        entries = [(rig.identity(obj.data.bones[name]), name, chain, order, base)
                   for name, chain, order, base in rows]
        remember_input(settings, "rotation_source", source)
        settings.affected.clear()
        for uid, name, chain, order, base in entries:
            item = settings.affected.add()
            item.name, item.bone_id, item.chain, item.order, item.base = name, uid, chain, order, base
    return report("Loaded", len(entries), names=[e[1] for e in entries])


def apply_falloff(context):
    obj = rig.require_rig(context)
    with rig.object_context(context):
        settings = obj.data.ozo_rotation_follow
        records, index = read_records(obj.data), rig.index_bones(obj.data)
        rows = affected(settings, index)
        values = distribution(settings, [b.name for _, b in rows], logical_parents(obj.data, records, index))
        by_name = {b.name: item for item, b in rows}
        for name, chain, order, base in values:
            item = by_name[name]
            item.chain, item.order, item.base = chain, order, base
        # Reorder the visible list as well as its chain/order labels, including
        # when a no-falloff preview was originally captured alphabetically.
        for position, (name, _, _, _) in enumerate(values):
            uid = obj.data.bones[name][rig.BONE_ID]
            old = next(i for i, item in enumerate(settings.affected) if item.bone_id == uid)
            if old != position:
                settings.affected.move(old, position)
    return report("Previewed", len(rows), names=[b.name for _, b in rows])


def validate_structure(record, index):
    controlled = rig.resolve(index, record["controlled"], "controlled bone")
    if record["mode"] == "DIRECT":
        return controlled
    if record["mch"] not in index:
        raise ValueError(f"MCH missing for {controlled.name}; use Recreate Missing to restore the deleted mechanism, then Connect Rotation")
    mch = index[record["mch"]]
    parent = rig.resolve(index, record["parent"], f"original parent of {controlled.name}") if record["parent"] else None
    if controlled.parent != mch or controlled.use_connect or mch.parent != parent or mch.use_connect:
        raise ValueError(f"Hierarchy changed for {controlled.name}; restore the recorded MCH parent before updating")
    if not rig.same_geometry(controlled, record["geometry"]):
        raise ValueError(f"Controlled rest geometry changed: {controlled.name}; MCH orientation/length edits are allowed, controller rest edits require rebuilding")
    return mch


def signature(constraint):
    return {field: getattr(constraint, field) for field in SIGNATURE_FIELDS}


def property_path(pose, name):
    return pose.path_from_id() + '["' + bpy.utils.escape_identifier(name) + '"]'


def driver_expression(record, base):
    return f"ozo_rf_{record['id'][:12]} * {float(base):.17g}"


def validate_property(pose, name):
    if name not in pose or isinstance(pose[name], bool) or not isinstance(pose[name], (int, float)):
        raise ValueError(f"Property must be a numeric scalar: {pose.name} / {name}")
    if not math.isfinite(float(pose[name])) or not 0 <= pose[name] <= 1:
        raise ValueError(f"Property value must be within 0..1: {pose.name} / {name}; existing values and ranges are never rewritten")


def validate_driver(obj, constraint, record, index):
    curve = rig.driver_for(obj, constraint.path_from_id("influence"))
    link = record["link"]
    if not link:
        if curve:
            raise ValueError(f"User driver conflicts with {constraint.name}; no driver ownership was recorded")
        if abs(constraint.influence - record["base"]) > 1e-6:
            raise ValueError(f"Influence edited outside Rotation Follow: {constraint.name}; restore it before updating")
        return
    bone = rig.resolve(index, link["bone"], "follow-property bone")
    validate_property(obj.pose.bones[bone.name], link["name"])
    if not curve:
        raise ValueError(f"Managed influence driver missing: {constraint.name}; restore it before updating")
    driver = curve.driver
    variables = list(driver.variables)
    correct = (driver.type == "SCRIPTED" and not driver.use_self and not curve.mute
               and not curve.modifiers and driver.expression == driver_expression(record, record["base"])
               and len(variables) == 1 and variables[0].name == "ozo_rf_" + record["id"][:12]
               and variables[0].type == "SINGLE_PROP")
    if correct:
        target = variables[0].targets[0]
        correct = target.id == obj and target.data_path == property_path(obj.pose.bones[bone.name], link["name"])
    if not correct:
        raise ValueError(f"Managed driver was edited or replaced: {constraint.name}; user drivers are not overwritten")


def managed_constraint(obj, record, index):
    owner = validate_structure(record, index)
    if not record["constraint"]:
        return owner, None
    pose = obj.pose.bones[owner.name]
    constraint = pose.constraints.get(record["constraint"])
    source = rig.resolve(index, record["source"], "recorded Rotation Source")
    if (constraint is None or constraint.type != "COPY_ROTATION" or constraint.target != obj
            or constraint.subtarget != source.name or signature(constraint) != record["options"]):
        raise ValueError(f"Managed constraint missing, renamed, edited or replaced on {owner.name}: {record['constraint']}")
    # Registry + stable bone/source identities + unique ownership token + full
    # native-settings/driver checks; a display name alone never grants ownership.
    token = "[" + record["id"][:12] + "]"
    if not constraint.name.endswith(token):
        raise ValueError(f"Constraint ownership token does not match: {owner.name}")
    prefix = constraint.path_from_id() + "."
    for curve in rig.animation_curves(obj):
        if curve.data_path.startswith(prefix):
            if (curve.data_path == constraint.path_from_id("influence") and record["link"]
                    and curve == rig.driver_for(obj, curve.data_path)):
                continue
            raise ValueError(f"Animated or user-driven constraint settings conflict: {owner.name} / {constraint.name}")
    validate_driver(obj, constraint, record, index)
    position = list(pose.constraints).index(constraint)
    if any(c.type == "STRETCH_TO" for c in list(pose.constraints)[:position]):
        raise ValueError(f"Rotation Follow was moved after Stretch To on {owner.name}; restore constraint order before updating")
    return owner, constraint


def validate_conflicts(obj, owner, managed=None):
    for constraint in obj.pose.bones[owner.name].constraints:
        if constraint != managed and constraint.type in {"COPY_ROTATION", "COPY_TRANSFORMS", "IK"}:
            raise ValueError(f"Existing user rotation mechanism on {owner.name}: {constraint.name}; resolve it before connecting")


def create_mch(context):
    obj = rig.require_rig(context)
    with rig.object_context(context), rig.RigTransaction(context, RECORD_KEY) as transaction:
        settings = obj.data.ozo_rotation_follow
        if settings.mode != "MCH":
            raise ValueError("Choose MCH Parent mode to create mechanisms")
        records, index = read_records(obj.data), rig.index_bones(obj.data)
        rows = affected(settings, index)
        validate_preview(settings, rows, records, obj.data, index)
        source = resolve_input(settings, "rotation_source", index, obj.data)
        if any(source == b for _, b in rows):
            raise ValueError(f"Rotation Source cannot also be affected: {source.name}")
        source_name = source.name
        controlled_names = [bone.name for _, bone in rows]
        collection = destination(obj.data, settings.specify_collection, settings.collection)
        if not math.isfinite(settings.mch_length) or settings.mch_length <= 0:
            raise ValueError("MCH length must be positive")
        specifications, existing, planned_parents, owners = [], [], {}, []
        for item, bone in rows:
            record = records["bindings"].get(item.bone_id)
            if record:
                if record["mode"] != "MCH":
                    raise ValueError(f"{bone.name} already has Direct Rotation Follow; structural mode switching requires an explicit rebuild")
                owner, constraint = managed_constraint(obj, record, index)
                owners.append(owner.name)
                existing.append(record)
                continue
            name = "MCH_ROT_" + rig.clean_base(bone.name)
            specifications.append({"controlled_name": bone.name, "controlled_id": item.bone_id,
                                   "mch_name": name, "mch_id": uuid.uuid4().hex,
                                   "length": settings.mch_length, "geometry": rig.rest_geometry(bone),
                                   "parent": bone.parent.name if bone.parent else None,
                                   "connected": bone.use_connect})
            planned_parents[name] = bone.parent.name if bone.parent else None
            planned_parents[bone.name] = name
            owners.append(name)
        validate_names(obj.data, [s["mch_name"] for s in specifications])
        rig.check_cycles(obj, source.name, owners, extra_parents=planned_parents)
        source_id = rig.identity(source)
        for spec in specifications:
            parent_id = rig.identity(obj.data.bones[spec["parent"]]) if spec["parent"] else None
            records["bindings"][spec["controlled_id"]] = {
                "id": uuid.uuid4().hex, "controlled": spec["controlled_id"], "source": source_id,
                "mode": "MCH", "mch": spec["mch_id"], "parent": parent_id,
                "original_connected": spec["connected"], "geometry": spec["geometry"],
                "constraint": None, "base": 1.0, "link": None,
            }
        if specifications:
            rig.insert_mch_parents(context, specifications, collection, transaction)
        save_records(obj.data, records)
        # Edit Mode synchronization reallocates Bone structs; do not retain a
        # Bone RNA reference across MCH insertion.
        remember_input(settings, "rotation_source", obj.data.bones[source_name])
    return report("Created MCH", len(specifications), skipped=len(existing), names=controlled_names)


def mch_edit_inputs(context):
    """Resolve the fixed controller list without rebuilding or changing sources."""
    obj = context.active_object
    settings = obj.data.ozo_rotation_follow
    if settings.mode != "MCH":
        raise ValueError("Choose MCH Parent mode for this operation")
    if not math.isfinite(settings.mch_length) or settings.mch_length <= 0:
        raise ValueError("MCH length must be positive")
    records, index = read_records(obj.data), rig.index_bones(obj.data)
    rows = affected(settings, index)
    prepared = []
    for item, bone in rows:
        record = records["bindings"].get(item.bone_id)
        if not record:
            raise ValueError(f"Create MCH first: {bone.name}")
        if record["mode"] != "MCH":
            raise ValueError(f"{bone.name} has a Direct binding; MCH maintenance does not switch structural modes")
        prepared.append((bone, record))
    return settings, records, index, prepared


def update_mch_length(context):
    obj = rig.require_rig(context)
    with rig.object_context(context), rig.RigTransaction(context, RECORD_KEY) as transaction:
        settings, records, index, prepared = mch_edit_inputs(context)
        changes, skipped = [], 0
        for controlled, record in prepared:
            mch = validate_structure(record, index)
            if abs(mch.length - settings.mch_length) < 1e-7:
                skipped += 1
                continue
            connected = [child.name for child in mch.children if child.use_connect]
            if connected:
                raise ValueError(f"Changing {mch.name} length would move Connected children: {', '.join(connected)}; disconnect them before updating")
            changes.append((mch.name, mch.length))
        if changes:
            transaction.watch_structure()
            from .bone_parenting import edit_active_armature
            with edit_active_armature(context, obj) as bones:
                for name, previous in changes:
                    bones[name].length = settings.mch_length
        context.view_layer.update()
    return report("Updated MCH length", len(changes), skipped=skipped,
                  names=[f"{name}: {old:.6g} -> {settings.mch_length:.6g}" for name, old in changes])


def recreate_missing_mch(context):
    """Explicitly recover deleted parents; never adopt a same-name replacement.

    Recovery only restores structure. The former constraint is marked pending
    and its verified property mapping is retained for a later Connect Rotation.
    """
    obj = rig.require_rig(context)
    with rig.object_context(context), rig.RigTransaction(context, RECORD_KEY) as transaction:
        settings, records, index, prepared = mch_edit_inputs(context)
        specifications, skipped, planned_parents = [], 0, {}
        for controlled, record in prepared:
            if record["mch"] in index:
                validate_structure(record, index)
                skipped += 1
                continue
            parent = rig.resolve(index, record["parent"], f"original parent of {controlled.name}") if record["parent"] else None
            if controlled.parent != parent:
                raise ValueError(f"Cannot recover {controlled.name}: current parent differs from its recorded original parent; restore that hierarchy first")
            if not rig.same_geometry(controlled, record["geometry"]):
                raise ValueError(f"Cannot recover {controlled.name}: controlled rest geometry changed after the MCH was deleted")
            source = rig.resolve(index, record["source"], f"recorded Rotation Source for {controlled.name}")
            if record["link"]:
                property_bone = rig.resolve(index, record["link"]["bone"], "follow-property bone")
                validate_property(obj.pose.bones[property_bone.name], record["link"]["name"])
            name = "MCH_ROT_" + rig.clean_base(controlled.name)
            specifications.append({"controlled_name": controlled.name, "controlled_id": record["controlled"],
                                   "mch_name": name, "mch_id": uuid.uuid4().hex,
                                   "length": settings.mch_length, "source_name": source.name})
            planned_parents[controlled.name] = name
            planned_parents[name] = parent.name if parent else None
        if specifications:
            collection = destination(obj.data, settings.specify_collection, settings.collection)
            # This also rejects orphan/user animation addressing proposed names;
            # such curves must not be silently erased or attached to new bones.
            validate_names(obj.data, [spec["mch_name"] for spec in specifications])
            for spec in specifications:
                rig.check_cycles(obj, spec["source_name"], [spec["mch_name"]], extra_parents=planned_parents)
            rig.insert_mch_parents(context, specifications, collection, transaction)
            for spec in specifications:
                record = records["bindings"][spec["controlled_id"]]
                record["mch"] = spec["mch_id"]
                record["constraint"] = None
                record.pop("options", None)
            save_records(obj.data, records)
        context.view_layer.update()
    return report("Recreated missing MCH", len(specifications), skipped=skipped,
                  names=[f"{s['controlled_name']} -> {s['mch_name']}; check orientation, then Connect Rotation" for s in specifications])


def write_driver(obj, constraint, record, index, base):
    link = record["link"]
    property_bone = rig.resolve(index, link["bone"], "follow-property bone")
    curve = constraint.driver_add("influence")
    driver = curve.driver
    driver.type, driver.use_self = "SCRIPTED", False
    for variable in list(driver.variables):
        driver.variables.remove(variable)
    variable = driver.variables.new()
    variable.name, variable.type = "ozo_rf_" + record["id"][:12], "SINGLE_PROP"
    variable.targets[0].id = obj
    variable.targets[0].data_path = property_path(obj.pose.bones[property_bone.name], link["name"])
    driver.expression = driver_expression(record, base)


def connect_rotation(context):
    obj = rig.require_rig(context)
    with rig.object_context(context), rig.RigTransaction(context, RECORD_KEY) as transaction:
        settings = obj.data.ozo_rotation_follow
        records, index = read_records(obj.data), rig.index_bones(obj.data)
        rows = affected(settings, index)
        validate_preview(settings, rows, records, obj.data, index)
        source = resolve_input(settings, "rotation_source", index, obj.data)
        if any(source == bone for _, bone in rows):
            raise ValueError(f"Rotation Source cannot also be affected: {source.name}")
        prepared = []
        for item, controlled in rows:
            record = records["bindings"].get(item.bone_id)
            if record:
                if record["mode"] != settings.mode:
                    raise ValueError(f"Mode differs from the recorded mechanism for {controlled.name}; ordinary updates cannot rebuild structure")
                owner, constraint = managed_constraint(obj, record, index)
            else:
                if settings.mode == "MCH":
                    raise ValueError(f"Create MCH before Connect Rotation: {controlled.name}")
                owner, constraint = controlled, None
            validate_conflicts(obj, owner, constraint)
            prepared.append((item, controlled, owner, constraint, record))
        rig.check_cycles(obj, source.name, [o.name for _, _, o, _, _ in prepared],
                         ignore={c.as_pointer() for _, _, _, c, _ in prepared if c})
        source_id = rig.identity(source)
        created = 0
        for item, controlled, owner, constraint, record in prepared:
            pose = obj.pose.bones[owner.name]
            if record is None:
                record = {"id": uuid.uuid4().hex, "controlled": item.bone_id, "source": source_id,
                          "mode": "DIRECT", "mch": None, "constraint": None, "base": 1.0, "link": None}
                records["bindings"][item.bone_id] = record
            if constraint is None:
                constraint = transaction.new_constraint(pose)
                constraint.name = "OZO Rotation Follow [" + record["id"][:12] + "]"
                position = next((i for i, c in enumerate(pose.constraints) if c.type == "STRETCH_TO"), None)
                if position is not None:
                    pose.constraints.move(len(pose.constraints) - 1, position)
                created += 1
            else:
                transaction.watch_constraint(pose, constraint)
            base = effective_base(settings, item)
            constraint.target, constraint.subtarget = obj, source.name
            for field in OPTION_FIELDS:
                setattr(constraint, field, getattr(settings, field))
            constraint.mute = False
            if record["link"]:
                write_driver(obj, constraint, record, index, base)
            else:
                constraint.influence = base
            record.update(source=source_id, constraint=constraint.name, base=base, options=signature(constraint))
        save_records(obj.data, records)
        remember_input(settings, "rotation_source", source)
        context.view_layer.update()
    return report("Connected", created, updated=len(prepared) - created, names=[b.name for _, b in rows])


def property_targets(context):
    obj = context.active_object
    settings = obj.data.ozo_rotation_follow
    records, index = read_records(obj.data), rig.index_bones(obj.data)
    rows = affected(settings, index)
    validate_preview(settings, rows, records, obj.data, index)
    prepared = []
    for item, bone in rows:
        record = records["bindings"].get(item.bone_id)
        if not record or record["mode"] != settings.mode or not record["constraint"]:
            raise ValueError(f"Connect Rotation first in the recorded mode: {bone.name}")
        owner, constraint = managed_constraint(obj, record, index)
        validate_conflicts(obj, owner, constraint)
        prepared.append((item, record, obj.pose.bones[owner.name], constraint))
    return settings, records, index, prepared


def connect_property(context):
    obj = rig.require_rig(context)
    with rig.object_context(context), rig.RigTransaction(context, RECORD_KEY) as transaction:
        settings, records, index, prepared = property_targets(context)
        bone = resolve_input(settings, "property_bone", index, obj.data)
        pose = obj.pose.bones[bone.name]
        name = settings.new_property.strip() if settings.property_mode == "NEW" else settings.existing_property
        if not name or name == "__NONE__" or len(name.encode("utf-8")) > 63 or name == "_RNA_UI":
            raise ValueError("Choose a property name of 1..63 UTF-8 bytes")
        exists = name in pose
        if settings.property_mode == "NEW" and exists:
            if not all(r["link"] and r["link"]["bone"] == bone.get(rig.BONE_ID)
                       and r["link"]["name"] == name for _, r, _, _ in prepared):
                raise ValueError(f"New property already exists: {pose.name} / {name}; choose Existing Property to share it")
        if exists:
            validate_property(pose, name)
        elif settings.property_mode != "NEW":
            raise ValueError(f"Existing property missing: {pose.name} / {name}")
        # A custom property is independent of its bone transform. Only inspect
        # actual transform-variable dependencies of an upstream property driver.
        upstream = rig.driver_for(obj, property_path(pose, name))
        if upstream:
            for dependency in rig.transform_dependencies(upstream.driver, obj):
                rig.check_cycles(obj, dependency, [p.name for _, _, p, _ in prepared],
                                 ignore={c.as_pointer() for _, _, _, c in prepared})
        if not exists:
            transaction.new_property(pose, name)
            pose[name] = 1.0
            pose.id_properties_ui(name).update(min=0.0, max=1.0, soft_min=0.0, soft_max=1.0, default=1.0)
        property_id = rig.identity(bone)
        index = rig.index_bones(obj.data)
        for item, record, owner, constraint in prepared:
            transaction.watch_constraint(owner, constraint)
            base = effective_base(settings, item)
            record["link"] = {"bone": property_id, "name": name}
            write_driver(obj, constraint, record, index, base)
            record["base"] = base
        save_records(obj.data, records)
        remember_input(settings, "property_bone", bone)
        context.view_layer.update()
    return report("Linked property", len(prepared), names=[p.name for _, _, p, _ in prepared])


def disconnect_property(context):
    obj = rig.require_rig(context)
    with rig.object_context(context), rig.RigTransaction(context, RECORD_KEY) as transaction:
        settings, records, index, prepared = property_targets(context)
        changed = 0
        for item, record, owner, constraint in prepared:
            if record["link"]:
                transaction.watch_constraint(owner, constraint)
                constraint.driver_remove("influence")
                constraint.influence = effective_base(settings, item)
                record.update(base=constraint.influence, link=None)
                changed += 1
        save_records(obj.data, records)
        context.view_layer.update()
    return report("Disconnected property", changed, skipped=len(prepared) - changed,
                  names=[p.name for _, _, p, _ in prepared])


def report(action, count, updated=0, skipped=0, names=()):
    return {"status": f"{action}: {count} | Updated: {updated} | Skipped: {skipped} | Conflicts: 0",
            "details": "\n".join(names)}


def auto_changed(settings, context):
    if not settings.auto_falloff:
        for item in settings.affected:
            item.base = 1.0


def source_changed(settings, context):
    settings.rotation_source_id = settings.rotation_source_label = ""


def property_bone_changed(settings, context):
    settings.property_bone_id = settings.property_bone_label = ""


_PROPERTY_ITEMS = {}
def property_items(settings, context):
    obj = context.active_object if context else None
    items = []
    if obj and obj.type == "ARMATURE":
        try:
            index = rig.index_bones(obj.data)
            bone = resolve_input(settings, "property_bone", index, obj.data)
            pose = obj.pose.bones[bone.name]
            items = [(key, key, "Existing numeric property; value, limits and animation are preserved")
                     for key in pose.keys() if not isinstance(pose[key], bool) and isinstance(pose[key], (int, float))]
        except ValueError:
            pass
    if not items:
        items = [("__NONE__", "No numeric properties", "Choose a property bone with an existing numeric custom property")]
    # Dynamic enum strings must remain alive for Blender's UI/RNA.
    _PROPERTY_ITEMS[settings.as_pointer()] = items
    return items


class OZO_PG_follow_bone(bpy.types.PropertyGroup):
    bone_id: StringProperty()
    chain: IntProperty()
    order: IntProperty()
    base: FloatProperty(name="Base Influence", default=1, min=0, max=1, precision=3)


class OZO_PG_rotation_follow(bpy.types.PropertyGroup):
    rotation_source: StringProperty(name="Rotation Source", description="Explicit source bone on this armature", update=source_changed)
    rotation_source_id: StringProperty()
    rotation_source_label: StringProperty()
    mode: EnumProperty(name="Mode", items=(("DIRECT", "Direct Constraint", "Copy Rotation on each affected bone"),
                                          ("MCH", "MCH Parent", "Insert clean parents, adjust them, then connect rotation")), default="DIRECT")
    auto_falloff: BoolProperty(name="Auto Falloff", default=False, update=auto_changed)
    start_influence: FloatProperty(name="Start Influence", default=0.2, min=0, max=1)
    end_influence: FloatProperty(name="End Influence", default=0.8, min=0, max=1)
    affected: CollectionProperty(type=OZO_PG_follow_bone)
    active_index: IntProperty()
    target_space: EnumProperty(name="Target Space", items=TARGET_SPACES, default="LOCAL")
    owner_space: EnumProperty(name="Owner Space", items=OWNER_SPACES, default="LOCAL")
    mix_mode: EnumProperty(name="Mix", items=MIX_MODES, default="REPLACE")
    use_x: BoolProperty(name="X", default=True)
    use_y: BoolProperty(name="Y", default=True)
    use_z: BoolProperty(name="Z", default=True)
    invert_x: BoolProperty(name="Invert X", default=False)
    invert_y: BoolProperty(name="Invert Y", default=False)
    invert_z: BoolProperty(name="Invert Z", default=False)
    show_options: BoolProperty(name="Constraint Options", default=False)
    mch_length: FloatProperty(name="MCH Length", default=0.3, min=0.00001, precision=4, subtype="DISTANCE", unit="LENGTH",
                             description="Length for Create/Recreate; use Update Length to apply it to existing MCH bones")
    specify_collection: BoolProperty(name="Specify Collection", default=False)
    collection: StringProperty(name="Collection")
    connect_follow_property: BoolProperty(name="Connect Follow Property", default=False)
    property_bone: StringProperty(name="Property Bone", update=property_bone_changed)
    property_bone_id: StringProperty()
    property_bone_label: StringProperty()
    property_mode: EnumProperty(name="Property", items=(("EXISTING", "Existing Property", "Use an existing numeric scalar"),
                                                      ("NEW", "New Property", "Create a float property with range 0..1 and value 1")), default="NEW")
    existing_property: EnumProperty(name="Existing Property", items=property_items)
    new_property: StringProperty(name="New Property", default="Rotation_Follow")
    last_status: StringProperty(options={"SKIP_SAVE"})
    last_details: StringProperty(options={"SKIP_SAVE"})


class FollowOperator:
    bl_options = {"REGISTER", "UNDO"}
    bl_translation_context = "OZO_Tools"

    @classmethod
    def poll(cls, context):
        try:
            rig.require_rig(context)
        except ValueError as error:
            cls.poll_message_set(str(error))
            return False
        return True

    def execute(self, context):
        settings = context.active_object.data.ozo_rotation_follow
        try:
            result = self.run(context)
        except (ValueError, RuntimeError, TypeError) as error:
            settings.last_status = "Processed: 0 | Conflicts: 1 | Rolled back"
            settings.last_details = str(error)
            print("[OZO Rotation Follow]", settings.last_status, str(error))
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        settings.last_status, settings.last_details = result["status"], result["details"]
        print("[OZO Rotation Follow]", result["status"], result["details"], sep="\n")
        self.report({"INFO"}, result["status"])
        return {"FINISHED"}


class OZO_OT_follow_load(FollowOperator, bpy.types.Operator):
    bl_idname = "ozo.follow_load_selected"
    bl_label = "Load Selected"
    bl_description = "Fix the affected list from the active armature's current selection; preview a fresh distribution"
    run = staticmethod(load_selected)


class OZO_OT_follow_falloff(FollowOperator, bpy.types.Operator):
    bl_idname = "ozo.follow_apply_falloff"
    bl_label = "Apply Falloff"
    bl_description = "Recompute preview coefficients by hierarchy; does not write constraints"
    run = staticmethod(apply_falloff)


class OZO_OT_follow_mch(FollowOperator, bpy.types.Operator):
    bl_idname = "ozo.follow_create_mch"
    bl_label = "Create MCH"
    bl_description = "Insert clean MCH parents; adjust their rest orientation/length before Connect Rotation"
    run = staticmethod(create_mch)


class OZO_OT_follow_mch_length(FollowOperator, bpy.types.Operator):
    bl_idname = "ozo.follow_update_mch_length"
    bl_label = "Update MCH Length"
    bl_description = "Apply MCH Length to existing mechanisms in the affected list, preserving head, direction, roll, constraints and drivers"
    run = staticmethod(update_mch_length)


class OZO_OT_follow_mch_recreate(FollowOperator, bpy.types.Operator):
    bl_idname = "ozo.follow_recreate_missing_mch"
    bl_label = "Recreate Missing MCH"
    bl_description = "Recover deleted MCHs at the chosen length using controlled rest orientation; keep existing MCHs and property mappings, then use Connect Rotation"
    run = staticmethod(recreate_missing_mch)


class OZO_OT_follow_connect(FollowOperator, bpy.types.Operator):
    bl_idname = "ozo.follow_connect_rotation"
    bl_label = "Connect Rotation"
    bl_description = "Create or update owned Copy Rotation constraints for the fixed affected list"
    run = staticmethod(connect_rotation)


class OZO_OT_follow_property(FollowOperator, bpy.types.Operator):
    bl_idname = "ozo.follow_connect_property"
    bl_label = "Connect Property"
    run = staticmethod(connect_property)


class OZO_OT_follow_unlink(FollowOperator, bpy.types.Operator):
    bl_idname = "ozo.follow_disconnect_property"
    bl_label = "Disconnect Property"
    bl_description = "Remove only owned influence drivers; restore previewed base coefficients, retain shared properties"
    run = staticmethod(disconnect_property)


class OZO_UL_follow_bones(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        bones = data.id_data.edit_bones if data.id_data.is_editmode else data.id_data.bones
        matches = [b for b in bones if b.get(rig.BONE_ID) == item.bone_id]
        name = matches[0].name if len(matches) == 1 else "Missing: " + item.name
        row = layout.split(factor=0.76, align=True)
        row.label(text=f"{item.chain + 1}.{item.order + 1}  {name}", translate=False)
        value = row.row()
        value.enabled = data.auto_falloff
        value.prop(item, "base", text="")


class OZO_PT_rotation_follow(bpy.types.Panel):
    bl_idname = "OZO_PT_rotation_follow"
    bl_label = "Rotation Follow"
    bl_parent_id = "OZO_PT_bone_controls"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OZO_Tools"
    bl_translation_context = "OZO_Tools"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 2

    def draw(self, context):
        outer = self.layout.row()
        spacer = outer.column()
        spacer.ui_units_x = 1.0
        spacer.label(text="")
        layout = outer.column()
        layout.use_property_decorate = False
        obj = context.active_object
        if not obj or obj.type != "ARMATURE":
            layout.label(text="Select an armature.", translate=False)
            return
        settings = obj.data.ozo_rotation_follow
        layout.label(text="Rotation Source", translate=False)
        layout.prop_search(settings, "rotation_source", obj.data, "bones", text="", translate=False)
        layout.prop(settings, "mode", text="Mode", translate=False)
        layout.operator("ozo.follow_load_selected", translate=False)
        layout.prop(settings, "auto_falloff", translate=False)
        if settings.auto_falloff:
            row = layout.row(align=True)
            row.prop(settings, "start_influence", text="Start", translate=False)
            row.prop(settings, "end_influence", text="End", translate=False)
            layout.operator("ozo.follow_apply_falloff", translate=False)
        layout.label(text=f"Affected Bones: {len(settings.affected)}", translate=False)
        if settings.affected:
            layout.template_list("OZO_UL_follow_bones", "", settings, "affected", settings, "active_index", rows=3, maxrows=6)
        if settings.mode == "MCH":
            layout.prop(settings, "mch_length", translate=False)
            layout.prop(settings, "specify_collection", translate=False)
            if settings.specify_collection:
                layout.prop_search(settings, "collection", obj.data, "collections_all", translate=False)
            else:
                active = obj.data.collections.active
                layout.label(text="Collection: " + (active.name if active else "None"), translate=False)
            layout.operator("ozo.follow_create_mch", translate=False)
            row = layout.row(align=True)
            row.operator("ozo.follow_update_mch_length", text="Update Length", translate=False)
            row.operator("ozo.follow_recreate_missing_mch", text="Recreate Missing", translate=False)
            layout.label(text="Adjust MCH in Edit Mode.", translate=False)
        layout.prop(settings, "show_options", icon="TRIA_DOWN" if settings.show_options else "TRIA_RIGHT", emboss=False, translate=False)
        if settings.show_options:
            box = layout.box()
            for field, label in (("target_space", "Target"), ("owner_space", "Owner"), ("mix_mode", "Mix")):
                box.prop(settings, field, text=label, translate=False)
            for prefix, label in (("use_", "Axes"), ("invert_", "Invert")):
                row = box.row(align=True)
                row.label(text=label, translate=False)
                for axis in "xyz":
                    row.prop(settings, prefix + axis, text=axis.upper(), toggle=True, translate=False)
        layout.operator("ozo.follow_connect_rotation", translate=False)
        layout.prop(settings, "connect_follow_property", translate=False)
        if settings.connect_follow_property:
            box = layout.box()
            box.label(text="Property Bone", translate=False)
            box.prop_search(settings, "property_bone", obj.data, "bones", text="", translate=False)
            box.prop(settings, "property_mode", translate=False)
            box.prop(settings, "new_property" if settings.property_mode == "NEW" else "existing_property", text="Name", translate=False)
            box.operator("ozo.follow_connect_property", translate=False)
            box.operator("ozo.follow_disconnect_property", translate=False)
        if settings.last_status:
            # Keep long counts/details in a popup rather than stretching the sidebar.
            row = layout.row()
            row.label(text="Last operation", translate=False)
            row.operator("ozo.follow_report", text="Details", translate=False)


class OZO_OT_follow_report(bpy.types.Operator):
    bl_idname = "ozo.follow_report"
    bl_label = "Rotation Follow Details"

    def execute(self, context):
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=650)

    def draw(self, context):
        settings = context.active_object.data.ozo_rotation_follow
        for line in settings.last_status.split(" | ") + settings.last_details.splitlines()[:30]:
            self.layout.label(text=line, translate=False)


CLASSES = (OZO_PG_follow_bone, OZO_PG_rotation_follow, OZO_OT_follow_load,
           OZO_OT_follow_falloff, OZO_OT_follow_mch, OZO_OT_follow_mch_length,
           OZO_OT_follow_mch_recreate, OZO_OT_follow_connect,
           OZO_OT_follow_property, OZO_OT_follow_unlink, OZO_UL_follow_bones,
           OZO_PT_rotation_follow, OZO_OT_follow_report)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Armature.ozo_rotation_follow = PointerProperty(type=OZO_PG_rotation_follow)


def unregister():
    del bpy.types.Armature.ozo_rotation_follow
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    _PROPERTY_ITEMS.clear()
