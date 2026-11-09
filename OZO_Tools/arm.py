# SPDX-License-Identifier: GPL-3.0-or-later
"""Five explicit Arm construction stages. No leg, parent switching or pose matching."""
from contextlib import contextmanager
import json
import math
import re
import uuid

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       FloatVectorProperty, PointerProperty, StringProperty)
from mathutils import Matrix, Vector

from . import rig_common as rig, bone_controls as controls
from .bone_parenting import edit_active_armature

RECORD_KEY = "ozo_arm_records"
ROLES = ("arm", "forearm", "hand")
INPUTS = tuple(p + r for r in ROLES for p in ("source_", "tweak_")) + ("tip",)
IK_FIELDS = ("target", "subtarget", "pole_target", "pole_subtarget", "chain_count",
             "pole_angle", "use_stretch", "use_tail", "iterations", "influence", "mute",
             "owner_space", "target_space", "space_object", "space_subtarget", "weight", "orient_weight",
             "reference_axis", "use_location", "lock_location_x", "lock_location_y", "lock_location_z",
             "use_rotation", "lock_rotation_x", "lock_rotation_y", "lock_rotation_z", "ik_type", "limit_mode", "distance")
COPY_FIELDS = ("target", "subtarget", "owner_space", "target_space", "mix_mode", "influence", "mute",
               "space_object", "space_subtarget", "head_tail", "use_bbone_shape", "remove_target_shear")
_VIS_COMMON = ("target", "subtarget", "head_tail", "owner_space", "target_space", "influence", "mute",
               "space_object", "space_subtarget", "use_bbone_shape")
VIS_FIELDS = {"COPY_LOCATION": _VIS_COMMON + ("use_x", "use_y", "use_z", "invert_x", "invert_y", "invert_z", "use_offset"),
              "STRETCH_TO": _VIS_COMMON + ("rest_length", "volume", "keep_axis", "bulge", "use_bulge_min",
                                          "use_bulge_max", "bulge_min", "bulge_max", "bulge_smooth")}
POSE_FIELDS = tuple("lock_ik_" + a for a in "xyz") + ("ik_stretch",)


def read_records(data):
    try:
        result = json.loads(data.get(RECORD_KEY, '{"version":1,"arms":{}}'))
        if result["version"] != 1 or not isinstance(result["arms"], dict):
            raise ValueError()
        for key, rec in result["arms"].items():
            if key != rec["id"] or set(rec["mapping"]) != set(INPUTS):
                raise ValueError()
            for field in ("names", "bones", "sources", "original_parents", "steps", "constraints", "link", "options"):
                if field not in rec:
                    raise ValueError()
            steps = rec["steps"]
            if (not isinstance(steps, list) or len(steps) != 5 or any(type(v) is not bool for v in steps)
                    or not steps[0] or steps != sorted(steps, reverse=True)):
                raise ValueError()
            expected = {"switch_" + role for role in ROLES}
            if steps[1]:
                expected.update(group + "_" + role for group in ("fk", "ik") for role in ROLES)
            if steps[2]:
                expected.update(("hand_control", "pole"))
                if rec["control_options"]["visual"]:
                    expected.add("visual")
            if set(rec["bones"]) != expected or set(rec["sources"]) != set(ROLES):
                raise ValueError()
            identities = list(rec["mapping"].values()) + list(rec["bones"].values())
            if any(not isinstance(v, str) or not v for v in identities) or len(set(identities)) != len(identities):
                raise ValueError()
            if not isinstance(rec["constraints"], list) or (steps[4] and not rec["link"]):
                raise ValueError()
            if rec["side"] not in {"", ".L", ".R"}:
                raise ValueError()
        return result
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("Invalid Arm records; restore a valid saved rig") from None


def save_records(data, records):
    data[RECORD_KEY] = json.dumps(records, ensure_ascii=False)


def result(created=0, updated=0, skipped=0, details=""):
    return {"status": f"Created: {created} | Updated: {updated} | Skipped: {skipped}", "details": details}


class ArmTransaction(rig.RigTransaction):
    def __init__(self, context):
        super().__init__(context, RECORD_KEY)
        self.pose_states = []
        self.arm_constraints = []
        self.had_animation = self.obj.animation_data is not None
        settings = self.obj.data.ozo_arm
        self.settings = {k: (tuple(getattr(settings, k)) if k == "pole_direction" else getattr(settings, k))
                         for k in settings.__annotations__ if k != "instances"}
        self.instances = [(item.name, item.uid) for item in settings.instances]

    def new_constraint(self, pose, kind):
        constraint = pose.constraints.new(kind)
        self.created_constraints.append((pose.name, constraint))
        return constraint

    def watch_arm_constraint(self, pose, constraint):
        fields = fields_for(constraint.type)
        self.arm_constraints.append((pose.name, constraint.name,
                                     {k: getattr(constraint, k) for k in fields}))

    def watch_pose(self, pose):
        self.pose_states.append((pose.name, {k: getattr(pose, k) for k in POSE_FIELDS}))

    def __exit__(self, kind, error, traceback):
        if kind is not None:
            for name, cname, fields in self.arm_constraints:
                for key, value in fields.items():
                    setattr(self.obj.pose.bones[name].constraints[cname], key, value)
            for name, fields in self.pose_states:
                for key, value in fields.items():
                    setattr(self.obj.pose.bones[name], key, value)
        value = super().__exit__(kind, error, traceback)
        if kind is not None and not self.had_animation and self.obj.animation_data and not self.obj.animation_data.drivers:
            self.obj.animation_data_clear()
        if kind is not None:
            settings = self.obj.data.ozo_arm
            for key, saved in self.settings.items():
                setattr(settings, key, saved)
            settings.instances.clear()
            for name, uid in self.instances:
                item = settings.instances.add()
                item.name, item.uid = name, uid
        return value


@contextmanager
def operation(context):
    context.view_layer.update()
    try:
        obj = rig.require_rig(context)
    except ValueError as error:
        raise ValueError(str(error).replace("Rotation Follow", "Arm")) from None
    with rig.object_context(context), ArmTransaction(context) as tx:
        yield obj, obj.data.ozo_arm, read_records(obj.data), tx


def input_bone(data, settings, field, index):
    name = getattr(settings, field)
    if name == getattr(settings, field + "_label") and getattr(settings, field + "_id"):
        return rig.resolve(index, getattr(settings, field + "_id"), field)
    bone = data.bones.get(name)
    if not bone:
        raise ValueError(f"Choose an existing bone for {field}: {name or '(empty)'}")
    return bone


def remember(settings, field, bone):
    setattr(settings, field, bone.name)
    setattr(settings, field + "_label", bone.name)
    setattr(settings, field + "_id", rig.identity(bone))


def generated_names(mapping):
    bases = {r: controls.base_name(mapping["source_" + r].name) for r in ROLES}
    sides = {side for _, side in bases.values()}
    if len(sides) != 1:
        raise ValueError("Arm / Forearm / Hand must have the same .L/.R suffix (or all no suffix)")
    names = {}
    for role, (stem, side) in bases.items():
        names["switch_" + role] = "MCH_Switch_" + stem + side
        names["fk_" + role] = stem + "_FK" + side
        names["ik_" + role] = "MCH_IK_" + stem + side
    stem, side = bases["hand"]
    names["hand_control"] = stem + "_IK" + side
    stem, side = bases["arm"]
    names["pole"] = stem + "_IK_POLE" + side
    names["visual"] = "VIS_" + stem + "_POLE" + side
    return names, side


def graph_check(obj, parents=None, edges=()):
    """Same-rig parent/constraint/transform-driver graph with proposed edges.

    Replacing a parent must retain the bone's other dependencies. IK also
    makes the upper solver bones depend on its targets, not only the owner.
    """
    hierarchy = {b.name: b.parent.name if b.parent else None for b in obj.data.bones}
    hierarchy.update(parents or {})
    graph = {name: {parent} if parent else set() for name, parent in hierarchy.items()}
    for pose in obj.pose.bones:
        for constraint in pose.constraints:
            targets = set()
            for target, name in ((getattr(constraint, "target", None), getattr(constraint, "subtarget", "")),
                                 (getattr(constraint, "pole_target", None), getattr(constraint, "pole_subtarget", ""))):
                if target == obj and name:
                    targets.add(name)
            for target in getattr(constraint, "targets", []):
                if target.target == obj and target.subtarget:
                    targets.add(target.subtarget)
            graph[pose.name].update(targets)
            if constraint.type == "IK":
                parent = hierarchy.get(pose.name)
                remaining = constraint.chain_count - 1 if constraint.chain_count else len(hierarchy)
                while parent and remaining > 0:
                    graph.setdefault(parent, set()).update(targets)
                    parent, remaining = hierarchy.get(parent), remaining - 1
    for curve in rig.animation_curves(obj):
        match = re.match(r'pose\.bones\["((?:[^"\\]|\\.)*)"\]', curve.data_path)
        if match and getattr(curve, "driver", None):
            owner = bpy.utils.unescape_identifier(match.group(1))
            graph.setdefault(owner, set()).update(rig.transform_dependencies(curve.driver, obj))
    for owner, source in edges:
        graph.setdefault(owner, set()).add(source)
    completed, visiting = set(), set()
    def visit(name):
        if name in visiting:
            raise ValueError("Arm dependency cycle involving " + str(name))
        if name in completed:
            return
        visiting.add(name)
        for dependency in graph.get(name, ()):
            visit(dependency)
        visiting.remove(name)
        completed.add(name)
    # Check only this Arm's proposed/touched graph or its ancestors, rather than
    # block construction because of an unrelated native solver elsewhere.
    starts = set(parents or {}) | {owner for owner, _ in edges}
    for name in starts:
        visit(name)


def make_bone(bones, name, geometry, parent, connected, collection, tx, uid):
    tx.created_bones.append(name)
    bone = bones.new(name)
    if bone.name != name:
        raise ValueError(f"Cannot create exact bone name: {name}")
    matrix = Matrix(geometry["matrix"])
    bone.head = matrix.translation
    bone.tail = bone.head + matrix.to_3x3().col[1] * geometry["length"]
    bone.matrix = matrix
    bone.length = geometry["length"]
    bone.parent = bones.get(parent) if parent else None
    bone.use_connect = connected
    bone.use_deform = False
    bone[rig.BONE_ID] = uid
    bone.select = bone.select_head = bone.select_tail = False
    for old in list(bone.collections):
        old.unassign(bone)
    collection.assign(bone)
    return bone


def active_record(settings, records):
    rec = records["arms"].get(settings.active_id)
    if rec is None:
        raise ValueError("Create Switch Chain or load an existing Arm instance first")
    index = rig.index_bones(settings.id_data)
    for field in INPUTS:
        bone = input_bone(settings.id_data, settings, field, index)
        if bone.get(rig.BONE_ID) != rec["mapping"][field]:
            raise ValueError(f"Mapping differs from active Arm: {field}; Load Arm Instance or Create Switch Chain for the new mapping first")
    return rec


def resolved(obj, rec):
    index = rig.index_bones(obj.data)
    return {key: rig.resolve(index, uid, key) for key, uid in {**rec["mapping"], **rec["bones"]}.items()}


def audit(obj, rec, through=5, repair_ik_setup=False):
    bones = resolved(obj, rec)
    for key in rec["bones"]:
        bone = bones[key]
        if bone.use_deform or bone.length <= rig.EPSILON or not all(math.isfinite(x) for row in bone.matrix_local for x in row):
            raise ValueError("Invalid generated rest bone or Deform enabled: " + bone.name)
    for role in ROLES:
        if not rig.same_geometry(bones["source_" + role], rec["sources"][role]):
            raise ValueError(f"Source rest geometry changed: {bones['source_' + role].name}; remap/rebuild explicitly")
    for group, step in (("switch", 1), ("fk", 2), ("ik", 2)):
        if not rec["steps"][step - 1] or step > through:
            continue
        for i, role in enumerate(ROLES):
            bone = bones[group + "_" + role]
            expected = bones[group + "_" + ROLES[i - 1]] if i else None
            if group == "ik" and role == "hand":
                if repair_ik_setup:
                    expected = bone.parent  # Explicit repair detaches just this target below.
                elif rec.get("ik_hand_detached"):
                    expected = None
            # Root parents are intentionally editable (e.g. a user-made Socket).
            if i and bone.parent != expected:
                raise ValueError(f"Hierarchy changed: {bone.name}; expected parent {expected.name if expected else 'None'}")
            connected = group == "ik" and role == "forearm"
            if bone.use_connect != connected:
                raise ValueError(f"Connected changed: {bone.name}; expected {connected}")
            if bone.use_deform:
                raise ValueError(f"Generated bone has Deform enabled: {bone.name}")
    for key in ("tweak_arm", "tweak_forearm", "tweak_hand", "tip"):
        parent = bones["switch_" + (key[6:] if key.startswith("tweak_") else "hand")]
        if bones[key].parent != parent or bones[key].use_connect:
            raise ValueError(f"Tweak hierarchy changed: {bones[key].name}; expected Keep Offset child of {parent.name}")
    if through >= 4:
        for saved in rec["constraints"]:
            managed_constraint(obj, rec, saved, repair_ik_setup=repair_ik_setup)
        if rec["steps"][3] and not repair_ik_setup:
            for role in ("arm", "forearm"):
                pose = obj.pose.bones[bones["ik_" + role].name]
                if any(abs(getattr(pose, k) - v) > 1e-7 for k, v in rec["options"][role].items()):
                    raise ValueError(f"IK bone settings changed outside Arm: {pose.name}; restore before updating")
    if not repair_ik_setup:
        graph_check(obj, {bones[k].name: bones[k].parent.name if bones[k].parent else None for k in rec["bones"]})
    return bones


def verify_mapping(obj, settings, rec):
    index = rig.index_bones(obj.data)
    for field in INPUTS:
        bone = input_bone(obj.data, settings, field, index)
        if bone.get(rig.BONE_ID) != rec["mapping"][field]:
            raise ValueError(f"Mapping differs from recorded Arm: {field}; load the instance or start a new mapping")


def create_switch(context):
    with operation(context) as (obj, settings, records, tx):
        index = rig.index_bones(obj.data)
        mapping = {k: input_bone(obj.data, settings, k, index) for k in INPUTS}
        if len({b.name for b in mapping.values()}) != len(INPUTS):
            raise ValueError("Each source, main Tweak and Tip must be a distinct explicitly mapped bone")
        existing = next((r for r in records["arms"].values() if r["mapping"]["source_arm"] == mapping["source_arm"].get(rig.BONE_ID)), None)
        if existing:
            verify_mapping(obj, settings, existing)
            audit(obj, existing)
            settings.active_id = existing["id"]
            sync_instances(obj.data, records)
            settings.instance = next(item.name for item in settings.instances if item.uid == existing["id"])
            return result(skipped=3, details="Switch chain already complete; rest edits retained. Load instance to inspect applied options.")
        used = {uid for r in records["arms"].values() for uid in r["mapping"].values()}
        if any(b.get(rig.BONE_ID) in used for b in mapping.values()):
            raise ValueError("Mapping overlaps another Arm instance; load that instance instead")
        names, side = generated_names(mapping)
        new_names = [names["switch_" + r] for r in ROLES]
        controls.validate_names(obj.data, new_names)
        collection = controls.destination(obj.data, settings.switch_use_collection, settings.switch_collection)
        for field, bone in mapping.items():
            if bone.length <= rig.EPSILON:
                raise ValueError(f"Zero/short mapped bone: {field} / {bone.name}")
        parent = mapping["tweak_arm"].parent
        if settings.parent_mode == "BONE":
            parent = input_bone(obj.data, settings, "switch_parent", index)
        elif settings.parent_mode == "NONE":
            parent = None
        parent_name = parent.name if parent else None
        planned = {names["switch_" + r]: names["switch_" + ROLES[i-1]] if i else parent_name for i, r in enumerate(ROLES)}
        planned.update({mapping["tweak_" + r].name: names["switch_" + r] for r in ROLES})
        planned[mapping["tip"].name] = names["switch_hand"]
        graph_check(obj, planned)
        # Identities are assigned only within the rollback boundary.
        rec = {"id": uuid.uuid4().hex, "side": side, "mapping": {k: rig.identity(b) for k, b in mapping.items()},
               "names": names, "bones": {}, "sources": {r: rig.rest_geometry(mapping["source_" + r]) for r in ROLES},
               "original_parents": {}, "steps": [True, False, False, False, False],
               "constraints": [], "options": {}, "link": None}
        for key in ("tweak_arm", "tweak_forearm", "tweak_hand", "tip"):
            bone = mapping[key]
            rec["original_parents"][key] = {"parent": rig.identity(bone.parent) if bone.parent else None, "connected": bone.use_connect}
        rec["initial_parent"] = rig.identity(parent) if parent else None
        mapping_names = {k: b.name for k, b in mapping.items()}
        rec["bones"] = {"switch_" + r: uuid.uuid4().hex for r in ROLES}
        tx.watch_structure()
        with edit_active_armature(context, obj) as bones:
            for role in ROLES:
                key = "switch_" + role
                make_bone(bones, names[key], rec["sources"][role], planned[names[key]], False, collection, tx, rec["bones"][key])
            for key in ("tweak_arm", "tweak_forearm", "tweak_hand", "tip"):
                bone = bones[mapping_names[key]]
                bone.use_connect = False
                bone.parent = bones[planned[bone.name]]
        records["arms"][rec["id"]] = rec
        save_records(obj.data, records)
        settings.active_id = rec["id"]
        for key, name in mapping_names.items():
            remember(settings, key, obj.data.bones[name])
        sync_instances(obj.data, records)
        settings.instance = next(item.name for item in settings.instances if item.uid == rec["id"])
    return result(created=3, updated=4, details="Switch: " + ", ".join(new_names) + "; 4 Tweak/Tip parents updated; no constraints added")


def create_chains(context):
    with operation(context) as (obj, settings, records, tx):
        rec = active_record(settings, records)
        bones = audit(obj, rec)
        if rec["steps"][1]:
            return result(skipped=6, details="FK / IK chains already complete; manual edits retained")
        names = rec["names"]
        controls.validate_names(obj.data, [names[g + "_" + r] for g in ("fk", "ik") for r in ROLES])
        collections = {g: controls.destination(obj.data, getattr(settings, g + "_use_collection"), getattr(settings, g + "_collection")) for g in ("fk", "ik")}
        geometry = {r: rig.rest_geometry(bones["switch_" + r]) for r in ROLES}
        if (bones["switch_arm"].tail_local - bones["switch_forearm"].head_local).length > rig.EPSILON:
            raise ValueError("Switch Arm tail and Forearm head do not coincide; cannot enable IK Connected without changing rest geometry")
        parent = bones["switch_arm"].parent
        parent_name = parent.name if parent else None
        planned = {names[g + "_" + r]: names[g + "_" + ROLES[i-1]] if i else parent_name for g in ("fk", "ik") for i, r in enumerate(ROLES)}
        planned[names["ik_hand"]] = None
        rec["ik_hand_detached"] = True
        graph_check(obj, planned)
        rec["chain_parent_at_creation"] = rig.identity(parent) if parent else None
        tx.watch_structure()
        with edit_active_armature(context, obj) as edits:
            for group in ("fk", "ik"):
                for role in ROLES:
                    key = group + "_" + role
                    uid = rec["bones"][key] = uuid.uuid4().hex
                    make_bone(edits, names[key], geometry[role], planned[names[key]], group == "ik" and role == "forearm", collections[group], tx, uid)
        rec["steps"][1] = True
        save_records(obj.data, records)
    return result(created=6, details="Parallel FK / IK roots use current Switch parent: " + str(parent_name))


def positive(value, label):
    if not math.isfinite(value) or value <= rig.EPSILON:
        raise ValueError(label + " must be positive and finite")
    return value


def bend_direction(a, b, c):
    line = c - a
    if line.length <= rig.EPSILON:
        raise ValueError("Shoulder and wrist coincide; no reliable bend plane")
    direction = b - a - line * ((b - a).dot(line) / line.length_squared)
    if direction.length <= max((b - a).length, (c - b).length) * 1e-4:
        raise ValueError("Arm is nearly straight; rest bend direction is degenerate. Correct rest bend or explicitly choose a Pole positioning direction")
    return direction.normalized()


def pole_position(obj, settings, bones):
    a, b, c = (bones[k].head_local.copy() for k in ("ik_arm", "ik_forearm", "ik_hand"))
    origin = b
    if settings.pole_direction_mode == "UPPER_X":
        upper = bones["ik_arm"]
        # Equivalent to duplicating the upper arm, translating along its local
        # X axis, and using that duplicate's tail as the Pole head. Do not
        # substitute the shoulder-wrist projection, nor the shortened Tweak.
        direction = upper.matrix_local.to_3x3().col[0].normalized()
        origin = upper.tail_local.copy()
    elif settings.pole_direction_mode == "EXPLICIT":
        direction = Vector(settings.pole_direction)
        if direction.length <= rig.EPSILON:
            raise ValueError("Explicit Pole direction must be nonzero (armature space)")
        line = c - a
        if line.length <= rig.EPSILON or direction.cross(line).length <= direction.length * line.length * 1e-4:
            raise ValueError("Explicit Pole direction is parallel to the shoulder-wrist line")
        direction.normalize()
    else:
        direction = bend_direction(a, b, c)
    distance = settings.pole_distance if settings.pole_distance > 0 else bones["ik_arm"].length
    positive(distance, "Pole Distance")
    return origin + direction * distance * (-1 if settings.flip_direction else 1), distance


def pole_axes(obj):
    """Extrude along world +Y; recalculate Roll against world +Z."""
    inverse = obj.matrix_world.to_3x3().inverted()
    return (inverse @ Vector((0, 1, 0))).normalized(), (inverse @ Vector((0, 0, 1))).normalized()


def create_controls(context):
    with operation(context) as (obj, settings, records, tx):
        rec = active_record(settings, records)
        bones = audit(obj, rec)
        if not rec["steps"][1]:
            raise ValueError("Create FK / IK Chains first")
        if rec["steps"][2]:
            if settings.create_visual != ("visual" in rec["bones"]):
                raise ValueError("Pole Visual structure differs from the created controls; creation never rebuilds structure")
            return result(skipped=3 if "visual" in bones else 2, details="IK controls already complete; manual rest positions/orientations retained")
        root = obj.data.bones.get(settings.root) if settings.root else None
        if not settings.root:
            matches = [b for b in obj.data.bones if b.name.casefold() == "root"]
            if len(matches) == 1:
                root = matches[0]
        if root is None:
            raise ValueError("Choose Root explicitly; automatic lookup needs exactly one ROOT/root/Root")
        keys = ["hand_control", "pole"] + (["visual"] if settings.create_visual else [])
        controls.validate_names(obj.data, [rec["names"][k] for k in keys])
        collection = controls.destination(obj.data, settings.control_use_collection, settings.control_collection)
        head, distance = pole_position(obj, settings, bones)
        length = positive(settings.pole_length, "Pole Length")
        axis, roll_axis = pole_axes(obj)
        geometry = rig.rest_geometry(bones["ik_hand"])
        elbow = bones["ik_forearm"].head_local.copy()
        root_name = root.name
        graph_check(obj, {rec["names"][k]: root_name if k != "visual" else None for k in keys},
                    [(bones["ik_forearm"].name, rec["names"][k]) for k in ("pole", "hand_control")])
        rec["control_root"] = rig.identity(root)
        tx.watch_structure()
        with edit_active_armature(context, obj) as edits:
            for key in keys:
                uid = rec["bones"][key] = uuid.uuid4().hex
                bone = make_bone(edits, rec["names"][key], geometry, root_name if key != "visual" else None, False, collection, tx, uid)
                if key == "pole":
                    bone.head, bone.tail = head, head + axis * length
                    bone.align_roll(roll_axis)
                elif key == "visual":
                    bone.head, bone.tail = elbow, head
        rec["steps"][2] = True
        rec["control_options"] = {"distance": distance, "flip": settings.flip_direction, "length": length,
                                  "direction_mode": settings.pole_direction_mode, "direction": list(settings.pole_direction), "visual": settings.create_visual,
                                  "orientation": "WORLD_Y_POS_Z"}
        save_records(obj.data, records)
    return result(created=len(keys), details="Adjust Hand IK / Pole in Edit Mode before Connect IK. Pole Distance=" + str(distance))


def fields_for(kind):
    return IK_FIELDS if kind == "IK" else COPY_FIELDS if kind == "COPY_TRANSFORMS" else VIS_FIELDS[kind]


def constraint_signature(obj, constraint):
    return {k: ("SELF" if getattr(constraint, k) == obj else getattr(constraint, k)) for k in fields_for(constraint.type) if k not in {"subtarget", "pole_subtarget"}}


def property_path(pose, name):
    return pose.path_from_id() + '["' + bpy.utils.escape_identifier(name) + '"]'


def validate_property(pose, name):
    if name not in pose or type(pose[name]) is not int or pose[name] not in (0, 1):
        raise ValueError(f"Switch property must be an integer 0/1: {pose.name} / {name}")
    ui = pose.id_properties_ui(name).as_dict()
    if ui.get("min") != 0 or ui.get("max") != 1:
        raise ValueError(f"Existing property range must be exactly 0..1: {pose.name} / {name}; value/range/animation are never reset")
    # Reuse is an explicit semantic opt-in in the UI; the description need not
    # have been authored by this addon, but contradictory labels are rejected.
    desc = ui.get("description", "").lower().replace(" ", "")
    if "0=ik" in desc or "1=fk" in desc:
        raise ValueError(f"Existing property describes reversed FK/IK semantics: {pose.name} / {name}")


def managed_constraint(obj, rec, saved, repair_ik_setup=False):
    index = rig.index_bones(obj.data)
    owner = rig.resolve(index, rec["bones"][saved["owner"]], saved["owner"])
    pose = obj.pose.bones[owner.name]
    c = pose.constraints.get(saved["name"])
    signature = constraint_signature(obj, c) if c and c.type == saved["type"] else None
    expected_signature = dict(saved["signature"])
    repairing_solver = repair_ik_setup and saved["owner"] == "ik_forearm" and saved["type"] == "IK"
    if signature and repairing_solver:
        for field in ("use_stretch", "pole_angle"):
            signature.pop(field, None)
            expected_signature.pop(field, None)
    if signature and saved.get("driven"):
        signature.pop("influence", None)
    if (c is None or c.type != saved["type"] or not c.name.endswith("[" + rec["id"][:12] + "]")
            or signature != expected_signature):
        raise ValueError(f"Managed constraint missing/renamed/edited: {owner.name} / {saved['name']}")
    for field, role in saved["targets"].items():
        target = rig.resolve(index, rec["bones"][role], role)
        if getattr(c, field) != target.name:
            if repairing_solver and field == "subtarget" and c.subtarget in {
                    rig.resolve(index, rec["bones"][role], role).name for role in ("hand_control", "ik_hand")}:
                continue
            raise ValueError(f"Managed constraint target changed: {owner.name} / {c.name}")
    prefix = c.path_from_id() + "."
    curve = rig.driver_for(obj, c.path_from_id("influence"))
    for fcurve in rig.animation_curves(obj):
        if fcurve.data_path.startswith(prefix) and not (saved.get("driven") and fcurve == curve):
            raise ValueError(f"Animation/user driver conflicts with owned constraint: {owner.name} / {c.name}")
    if saved.get("driven"):
        link = rec["link"]
        bone = rig.resolve(index, link["bone"], "Switch property bone")
        validate_property(obj.pose.bones[bone.name], link["name"])
        if curve is None:
            raise ValueError("Managed Switch driver missing: " + owner.name)
        variables = list(curve.driver.variables)
        if (curve.mute or curve.modifiers or curve.driver.type != "SCRIPTED" or curve.driver.use_self
                or curve.driver.expression != "ik_fk == 1" or len(variables) != 1
                or variables[0].type != "SINGLE_PROP" or variables[0].name != "ik_fk"
                or variables[0].targets[0].id != obj
                or variables[0].targets[0].data_path != property_path(obj.pose.bones[bone.name], link["name"])):
            raise ValueError("Managed Switch driver edited/replaced: " + owner.name)
    elif curve:
        raise ValueError("Foreign driver on Arm constraint: " + owner.name)
    if list(pose.constraints).index(c) != saved["order"]:
        raise ValueError(f"Managed constraint order changed: {owner.name} / {c.name}")
    return c


def record_constraint(obj, rec, owner, c, targets, driven=False):
    saved = {"owner": owner, "name": c.name, "type": c.type, "signature": constraint_signature(obj, c),
             "targets": targets, "driven": driven, "order": 0}
    if driven:
        saved["signature"].pop("influence", None)
    pose = obj.pose.bones[resolved(obj, rec)[owner].name]
    saved["order"] = list(pose.constraints).index(c)
    rec["constraints"].append(saved)
    return saved


def new_constraint(obj, rec, tx, owner, kind, label, target_role):
    bones = resolved(obj, rec)
    pose = obj.pose.bones[bones[owner].name]
    c = tx.new_constraint(pose, kind)
    c.name = label + " [" + rec["id"][:12] + "]"
    c.target, c.subtarget = obj, bones[target_role].name
    if kind == "COPY_TRANSFORMS":
        c.owner_space = c.target_space = "WORLD"
        c.mix_mode = "REPLACE"
    c.influence = 1
    return c


def check_owner_conflicts(obj, rec, keys):
    bones = resolved(obj, rec)
    managed = {s["name"] for s in rec["constraints"]}
    for key in keys:
        pose = obj.pose.bones[bones[key].name]
        foreign = [c.name for c in pose.constraints if c.name not in managed]
        if foreign:
            raise ValueError(f"Existing user constraints on {pose.name}: {', '.join(foreign)}; resolve before connecting")
        path = pose.path_from_id()
        for curve in rig.animation_curves(obj):
            if curve.data_path.startswith(path + ".") and not curve.data_path.startswith(path + ".constraints["):
                raise ValueError(f"Animated/driven mechanism owner conflicts: {pose.name} / {curve.data_path}")


def ik_options(settings):
    if settings.bend_axis == "NONE":
        raise ValueError("Choose Bend Axis explicitly (local X, Y or Z); no side-based axis guess is made")
    for value in (settings.arm_stretch, settings.forearm_stretch, settings.pole_angle):
        if not math.isfinite(value):
            raise ValueError("IK parameters must be finite")
    # Shoulder is a ball joint. Only the elbow is a one-axis hinge; applying
    # the elbow locks to the upper arm prevents a reachable hand target from
    # being reached by rotation and lets native IK Stretch hide that failure.
    return {role: {**{"lock_ik_" + a: role == "forearm" and a.upper() != settings.bend_axis for a in "xyz"},
                   "ik_stretch": getattr(settings, role + "_stretch")} for role in ("arm", "forearm")}


def connect_ik(context):
    return apply_ik(context, update=False)


def update_ik(context):
    return apply_ik(context, update=True)


def repair_ik(context):
    """Adopt native elbow/stretch choices, release shoulder locks and repair the owned target."""
    return apply_ik(context, update=True, repair_setup=True)


def apply_ik(context, update=False, repair_setup=False):
    with operation(context) as (obj, settings, records, tx):
        rec = active_record(settings, records)
        bones = audit(obj, rec, repair_ik_setup=repair_setup)
        if not rec["steps"][2]:
            raise ValueError("Create IK Controls first")
        if rec["steps"][3] and not update:
            return result(skipped=2 + (2 if "visual" in bones else 0), details="IK already connected; use Update IK Parameters or Match Rest Bend")
        if update and not rec["steps"][3] and not repair_setup:
            raise ValueError("Connect IK first")
        if repair_setup and rec["steps"][3]:
            forearm = obj.pose.bones[bones["ik_forearm"].name]
            unlocked = [a.upper() for a in "xyz" if not getattr(forearm, "lock_ik_" + a)]
            if len(unlocked) != 1:
                raise ValueError("Repair requires exactly one native elbow IK axis unlocked; choose the intended elbow axis in Bone IK settings first")
            saved_ik = next(s for s in rec["constraints"] if s["type"] == "IK")
            current_ik = managed_constraint(obj, rec, saved_ik, repair_ik_setup=True)
            settings.bend_axis = unlocked[0]
            settings.enable_stretch, settings.pole_angle = current_ik.use_stretch, current_ik.pole_angle
            settings.arm_stretch = obj.pose.bones[bones["ik_arm"].name].ik_stretch
            settings.forearm_stretch = forearm.ik_stretch
        elif repair_setup:
            update = False  # An old saved stage-3 rig can be migrated and connected explicitly.
        elif update and not rec.get("ik_hand_detached"):
            raise ValueError("Legacy IK target hierarchy: use Sync / Repair IK Setup before numerical updates")
        options = ik_options(settings)
        owners = ["ik_arm", "ik_forearm", "ik_hand"] + (["visual"] if "visual" in bones else [])
        check_owner_conflicts(obj, rec, owners)
        if not rec.get("ik_hand_detached") or bones["ik_hand"].parent is not None:
            hand_name = bones["ik_hand"].name
            tx.watch_structure()
            with edit_active_armature(context, obj) as edits:
                edits[hand_name].use_connect = False
                edits[hand_name].parent = None
            rec["ik_hand_detached"] = True
            bones = resolved(obj, rec)
        graph_check(obj, edges=[(bones["ik_forearm"].name, bones[k].name) for k in ("pole", "ik_hand")] + [(bones["ik_arm"].name, bones[k].name) for k in ("pole", "ik_hand")] + [(bones["ik_hand"].name, bones["hand_control"].name)])
        for role in ("arm", "forearm"):
            pose = obj.pose.bones[bones["ik_" + role].name]
            tx.watch_pose(pose)
            for key, value in options[role].items():
                setattr(pose, key, value)
        if update:
            saved = next(s for s in rec["constraints"] if s["type"] == "IK")
            ik = managed_constraint(obj, rec, saved, repair_ik_setup=repair_setup)
            tx.watch_arm_constraint(obj.pose.bones[bones["ik_forearm"].name], ik)
        else:
            ik = new_constraint(obj, rec, tx, "ik_forearm", "IK", "OZO Arm IK", "ik_hand")
            ik.pole_target, ik.pole_subtarget = obj, bones["pole"].name
            ik.chain_count, ik.iterations = 2, 500
        ik.use_stretch, ik.pole_angle = settings.enable_stretch, settings.pole_angle
        ik.subtarget = bones["ik_hand"].name
        if update:
            saved["signature"] = constraint_signature(obj, ik)
            saved["targets"]["subtarget"] = "ik_hand"
        else:
            record_constraint(obj, rec, "ik_forearm", ik, {"subtarget": "ik_hand", "pole_subtarget": "pole"})
            hand = new_constraint(obj, rec, tx, "ik_hand", "COPY_TRANSFORMS", "OZO Hand IK", "hand_control")
            record_constraint(obj, rec, "ik_hand", hand, {"subtarget": "hand_control"})
            if "visual" in bones:
                c = new_constraint(obj, rec, tx, "visual", "COPY_LOCATION", "OZO Pole Start", "ik_forearm")
                c.owner_space = c.target_space = "WORLD"
                c.head_tail = 0
                record_constraint(obj, rec, "visual", c, {"subtarget": "ik_forearm"})
                c = new_constraint(obj, rec, tx, "visual", "STRETCH_TO", "OZO Pole Aim", "pole")
                c.rest_length = bones["visual"].length
                c.volume = "NO_VOLUME"
                record_constraint(obj, rec, "visual", c, {"subtarget": "pole"})
        rec["steps"][3] = True
        rec["options"] = options
        rec["ik_parameters"] = {"bend_axis": settings.bend_axis, "enable_stretch": settings.enable_stretch, "pole_angle": ik.pole_angle}
        rec["solver_model"] = "SHOULDER_FREE_ELBOW_HINGE"
        rec.pop("calibration", None)
        save_records(obj.data, records)
        obj.update_tag()
        context.view_layer.update()
    details = (f"IK setup repaired: shoulder XYZ unlocked; retained native elbow {settings.bend_axis}, Stretch={settings.enable_stretch}, stretch weights and Pole Angle. "
               "IK target is the unparented MCH IK Hand; Copy Transforms still follows Hand IK. Bones/controls/constraints/drivers retained." if repair_setup else
               "IK branch connected: shoulder XYZ rotation unlocked; Bend Axis locks apply only to the elbow. Use Match Rest Bend to calibrate the rest bend. Native Enable Stretch allows compression as well as extension.")
    return result(created=0 if update else 2 + (2 if "visual" in bones else 0), updated=3 if update else 2, details=details)


def calibration_angle(context, obj, rec):
    """Search Pole Angle on a disposable, actually evaluated rest rig."""
    context.view_layer.update()
    bones = resolved(obj, rec)
    linear = obj.matrix_world.to_3x3()
    scales = [linear.col[i].length for i in range(3)]
    if (linear.determinant() <= 0 or max(scales) - min(scales) > max(scales) * 1e-5
            or any(abs(linear.col[i].normalized().dot(linear.col[j].normalized())) > 1e-5 for i in range(3) for j in range(i))):
        raise ValueError("Match Rest Bend supports positive uniform object scale and rotation; nonuniform scale, reflection or shear is unsupported")
    for role in ("ik_arm", "ik_forearm"):
        pose = obj.pose.bones[bones[role].name]
        if max(abs(pose.matrix_basis[i][j] - (1 if i == j else 0)) for i in range(4) for j in range(4)) > 1e-5:
            raise ValueError("Match Rest Bend requires neutral IK mechanism pose channels: " + pose.name)
        if any(getattr(pose, "use_ik_limit_" + a) or getattr(pose, "ik_stiffness_" + a) > 1e-7 for a in "xyz"):
            raise ValueError("Match Rest Bend does not support additional IK limits/stiffness: " + pose.name)
    ancestor = bones["ik_arm"].parent
    while ancestor:
        pose = obj.pose.bones[ancestor.name]
        if pose.constraints or max(abs(pose.matrix[i][j] - ancestor.matrix_local[i][j]) for i in range(4) for j in range(4)) > 2e-5:
            raise ValueError("Match Rest Bend requires IK root ancestors at rest without constraints: " + ancestor.name)
        ancestor = ancestor.parent
    a, b, c = (bones[k].head_local.copy() for k in ("ik_arm", "ik_forearm", "ik_hand"))
    if (bones["ik_forearm"].tail_local - c).length > rig.EPSILON:
        raise ValueError("Match Rest Bend requires Forearm tail at Hand head")
    bend_direction(a, b, c)  # A truly straight rest chain has no reference bend.
    evaluated = obj.evaluated_get(context.evaluated_depsgraph_get())
    pole = evaluated.pose.bones[bones["pole"].name].head.copy()
    target = evaluated.pose.bones[bones["ik_hand" if rec.get("ik_hand_detached") else "hand_control"].name].head.copy()
    # If Hand IK was manually adjusted, use its actual evaluated target and
    # project the rest elbow direction onto the new shoulder-target line.
    reference = bend_direction(a, b, target)
    upper, lower = bones["ik_arm"].length, bones["ik_forearm"].length
    reach = (target - a).length
    span = upper + lower
    if reach >= span * (1 - 1e-4) or reach <= abs(upper - lower) + span * 1e-4:
        raise ValueError("Hand IK target is at a straight/folded or unreachable position; place it within the bent two-bone reach before matching")
    along = (upper * upper - lower * lower + reach * reach) / (2 * reach)
    expected_elbow = a + (target - a).normalized() * along + reference * math.sqrt(max(0, upper * upper - along * along))
    try:
        bend_direction(a, pole, target)
    except ValueError:
        raise ValueError("Pole is on/too close to shoulder-wrist line; move Pole away before matching") from None
    data = bpy.data.armatures.new("__OZO_Arm_Calibration")
    probe = bpy.data.objects.new("__OZO_Arm_Calibration", data)
    context.scene.collection.objects.link(probe)
    active = context.view_layer.objects.active
    selected = list(context.selected_objects)
    try:
        for item in selected:
            item.select_set(False)
        probe.select_set(True)
        context.view_layer.objects.active = probe
        with edit_active_armature(context, probe) as edits:
            for i, key in enumerate(("ik_arm", "ik_forearm")):
                bone = edits.new(key)
                bone.head = bones[key].head_local
                bone.tail = bones[key].tail_local
                bone.matrix = bones[key].matrix_local
                bone.length = bones[key].length
                if i:
                    bone.parent = edits["ik_arm"]
                    bone.use_connect = True
            for key, head in (("target", target), ("pole", pole)):
                bone = edits.new(key)
                bone.head, bone.tail = head, head + Vector((0, 0, 0.2))
        for role in ("arm", "forearm"):
            for key, value in rec["options"][role].items():
                setattr(probe.pose.bones["ik_" + role], key, value)
        ik = probe.pose.bones["ik_forearm"].constraints.new("IK")
        ik.target, ik.subtarget = probe, "target"
        ik.pole_target, ik.pole_subtarget = probe, "pole"
        ik.chain_count, ik.iterations = 2, 500
        ik.use_stretch = rec["ik_parameters"]["enable_stretch"]

        def sample(angle):
            ik.pole_angle = (angle + math.pi) % (2 * math.pi) - math.pi
            probe.update_tag(refresh={"OBJECT"})
            context.view_layer.update()
            posed = probe.evaluated_get(context.evaluated_depsgraph_get()).pose.bones
            elbow = posed["ik_forearm"].head.copy()
            wrist = posed["ik_forearm"].tail.copy()
            error = ((elbow - expected_elbow).length_squared + (wrist - target).length_squared) / (span * span)
            return error, elbow, wrist

        count = 64
        grid = [(sample(-math.pi + i * 2 * math.pi / count)[0], -math.pi + i * 2 * math.pi / count) for i in range(count)]
        _, best = min(grid)
        left, right = best - 2 * math.pi / count, best + 2 * math.pi / count
        ratio = (math.sqrt(5) - 1) / 2
        x, y = right - ratio * (right - left), left + ratio * (right - left)
        fx, fy = sample(x)[0], sample(y)[0]
        for _ in range(30):
            if fx < fy:
                right, y, fy = y, x, fx
                x = right - ratio * (right - left)
                fx = sample(x)[0]
            else:
                left, x, fx = x, y, fy
                y = left + ratio * (right - left)
                fy = sample(y)[0]
        angle = (0.5 * (left + right) + math.pi) % (2 * math.pi) - math.pi
        error, elbow, wrist = sample(angle)
        dot = bend_direction(a, elbow, wrist).dot(reference)
        positional_error = (wrist - target).length / span
        if not math.isfinite(error) or dot < 0.9999 or positional_error > 0.002:
            raise ValueError(f"Rest bend verification failed (direction dot={dot:.6f}, relative position error={positional_error:.6g}); check Bend Axis, rolls and Pole position. Pole Angle was not changed")
        return angle, {"direction_dot": dot, "relative_position_error": positional_error, "samples": count + 33,
                       "reference_direction": list(reference), "expected_elbow": list(elbow),
                       "target": list(target), "shoulder": list(a), "span": span}
    finally:
        if probe.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.data.objects.remove(probe, do_unlink=True)
        bpy.data.armatures.remove(data)
        context.view_layer.objects.active = active
        for item in selected:
            item.select_set(True)


def match_rest_bend(context):
    with operation(context) as (obj, settings, records, tx):
        rec = active_record(settings, records)
        audit(obj, rec)
        if not rec["steps"][3]:
            raise ValueError("Connect IK before Match Rest Bend")
        angle, metrics = calibration_angle(context, obj, rec)
        saved = next(s for s in rec["constraints"] if s["type"] == "IK")
        ik = managed_constraint(obj, rec, saved)
        owner = resolved(obj, rec)["ik_forearm"]
        tx.watch_arm_constraint(obj.pose.bones[owner.name], ik)
        ik.pole_angle = angle
        saved["signature"] = constraint_signature(obj, ik)
        rec["ik_parameters"]["pole_angle"] = float(ik.pole_angle)
        obj.update_tag()
        context.view_layer.update()
        actual = obj.evaluated_get(context.evaluated_depsgraph_get()).pose.bones[owner.name]
        dot = bend_direction(Vector(metrics["shoulder"]), actual.head, actual.tail).dot(Vector(metrics["reference_direction"]))
        error = max((actual.head - Vector(metrics["expected_elbow"])).length, (actual.tail - Vector(metrics["target"])).length) / metrics["span"]
        if dot < 0.9999 or error > 0.002 or not math.isfinite(error):
            raise ValueError(f"Actual IK verification failed: direction dot={dot:.6f}, relative position error={error:.6g}; unsupported external mechanism or unstable solver. Pole Angle restored")
        metrics.update(live_direction_dot=dot, live_relative_position_error=error)
        rec["calibration"] = metrics
        save_records(obj.data, records)
        settings.pole_angle = ik.pole_angle
    return result(updated=1, details=f"Matched Pole Angle={math.degrees(angle):.5f} degrees; evaluated direction dot={metrics['direction_dot']:.8f}; relative position error={metrics['relative_position_error']:.6g}. Only owned IK Pole Angle was written.")


def connect_switch(context):
    with operation(context) as (obj, settings, records, tx):
        rec = active_record(settings, records)
        bones = audit(obj, rec)
        if not rec["steps"][3]:
            raise ValueError("Connect IK first")
        if rec["steps"][4]:
            return result(skipped=6, details="IK/FK Switch already connected; property value and drivers retained")
        check_owner_conflicts(obj, rec, ["switch_" + r for r in ROLES])
        holder = input_bone(obj.data, settings, "property_bone", rig.index_bones(obj.data))
        pose = obj.pose.bones[holder.name]
        name = settings.property_name.strip() or "Arm_FK_IK" + rec["side"]
        if settings.property_mode == "EXISTING":
            if not settings.confirm_semantics:
                raise ValueError("Confirm existing property semantics: 0=FK, 1=IK")
            validate_property(pose, name)
        else:
            if name in pose:
                raise ValueError(f"Property already exists: {pose.name} / {name}; choose Existing to reuse it explicitly")
            path = property_path(pose, name)
            if any(curve.data_path == path for curve in rig.animation_curves(obj)):
                raise ValueError("Existing animation/driver addresses proposed new property: " + path)
        graph_check(obj, edges=[(bones["switch_" + r].name, bones[g + "_" + r].name) for r in ROLES for g in ("fk", "ik")])
        if settings.property_mode == "NEW":
            tx.new_property(pose, name)
            pose[name] = 0
            pose.id_properties_ui(name).update(min=0, max=1, soft_min=0, soft_max=1, default=0,
                                              description="Arm IK/FK: 0=FK, 1=IK. Construction switch; no animation pose matching.")
        rec["link"] = {"bone": rig.identity(holder), "name": name, "created": settings.property_mode == "NEW"}
        path = property_path(pose, name)
        for role in ROLES:
            owner = "switch_" + role
            fk = new_constraint(obj, rec, tx, owner, "COPY_TRANSFORMS", "OZO FK", "fk_" + role)
            record_constraint(obj, rec, owner, fk, {"subtarget": "fk_" + role})
            ik = new_constraint(obj, rec, tx, owner, "COPY_TRANSFORMS", "OZO IK", "ik_" + role)
            curve = ik.driver_add("influence")
            driver = curve.driver
            driver.type, driver.use_self = "SCRIPTED", False
            variable = driver.variables.new()
            variable.name, variable.type = "ik_fk", "SINGLE_PROP"
            variable.targets[0].id = obj
            variable.targets[0].data_path = path
            driver.expression = "ik_fk == 1"
            record_constraint(obj, rec, owner, ik, {"subtarget": "ik_" + role}, driven=True)
        rec["steps"][4] = True
        save_records(obj.data, records)
        remember(settings, "property_bone", obj.data.bones[holder.name])
        obj.update_tag()
        context.view_layer.update()
    return result(created=6, updated=3, details=f"Three influence drivers share {pose.name} / {name}; initial mode={'IK' if pose[name] else 'FK'}; FK=1, then IK=(ik_fk == 1)")


def sync_instances(data, records):
    settings = data.ozo_arm
    settings.instances.clear()
    index = rig.index_bones(data)
    for rec in records["arms"].values():
        item = settings.instances.add()
        bone = index.get(rec["mapping"]["source_arm"])
        item.name = (bone.name if bone else "Missing Arm") + " [" + rec["id"][:8] + "]"
        item.uid = rec["id"]


def load_instance(context):
    with operation(context) as (obj, settings, records, tx):
        previous = settings.instances.get(settings.instance)
        selected_uid = previous.uid if previous else None
        sync_instances(obj.data, records)
        item = settings.instances.get(settings.instance)
        uid = selected_uid or (item.uid if item else settings.active_id)
        rec = records["arms"].get(uid)
        if rec is None:
            raise ValueError("Choose a recorded Arm instance")
        bones = audit(obj, rec)
        for key in INPUTS:
            remember(settings, key, bones[key])
        if "control_options" in rec:
            opts = rec["control_options"]
            settings.pole_distance, settings.pole_length = opts["distance"], opts["length"]
            settings.flip_direction, settings.create_visual = opts["flip"], opts["visual"]
            settings.pole_direction_mode, settings.pole_direction = opts["direction_mode"], opts["direction"]
        if rec["steps"][3]:
            for key, value in rec["ik_parameters"].items():
                setattr(settings, key, value)
            settings.arm_stretch = rec["options"]["arm"]["ik_stretch"]
            settings.forearm_stretch = rec["options"]["forearm"]["ik_stretch"]
        if rec["link"]:
            holder = rig.resolve(rig.index_bones(obj.data), rec["link"]["bone"], "property bone")
            remember(settings, "property_bone", holder)
            settings.property_name = rec["link"]["name"]
        settings.active_id = uid
        settings.instance = next(item.name for item in settings.instances if item.uid == uid)
    return result(skipped=sum(rec["steps"]), details="Loaded recorded mappings and applied IK options. Completed stages verified; rest edits retained.")


def new_mapping(context):
    obj = rig.require_rig(context)
    settings = obj.data.ozo_arm
    settings.active_id, settings.instance = "", ""
    for key in INPUTS:
        for suffix in ("", "_label", "_id"):
            setattr(settings, key + suffix, "")
    settings.property_name = ""
    settings.create_visual = True
    settings.pole_distance = 0
    settings.pole_direction_mode = "UPPER_X"
    return result(details="New Arm mapping; existing Arm instances remain recorded")


def load_tweak_mapping(context):
    obj = rig.require_rig(context)
    names = controls.selected_names(context)
    with operation(context) as (obj, settings, records, tx):
        identities = {obj.data.bones[n].get(controls.ID_KEY) for n in names}
        chains = [c for c in controls.read_records(obj.data)["chains"]
                  if identities & ({c["tip"]} | {e[k] for e in c["entries"] for k in ("source", "tweak", "fk")})]
        if len(chains) != 1 or len(chains[0]["entries"]) != 3:
            raise ValueError("Select a member of one recorded three-bone Tweak chain; otherwise fill the seven role mappings manually")
        chain = chains[0]
        index = {}
        for bone in obj.data.bones:
            value = bone.get(controls.ID_KEY)
            if value:
                if value in index:
                    raise ValueError("Duplicated Tweak identity: " + bone.name)
                index[value] = bone
        inputs = {p + r: e[k] for r, e in zip(ROLES, chain["entries"]) for p, k in (("source_", "source"), ("tweak_", "tweak"))}
        inputs["tip"] = chain["tip"]
        if any(uid not in index for uid in inputs.values()):
            raise ValueError("Recorded Tweak chain has missing members; fill mapping explicitly")
        for field, uid in inputs.items():
            remember(settings, field, index[uid])
        settings.active_id = ""
        settings.instance = ""
    return result(updated=7, details="Loaded Tweak record order as Arm / Forearm / Hand; inspect all roles and Tip before creating Switch")


def update_controls(context, align_upper_x=False):
    with operation(context) as (obj, settings, records, tx):
        rec = active_record(settings, records)
        bones = audit(obj, rec)
        if not rec["steps"][2]:
            raise ValueError("Create IK Controls first")
        if settings.create_visual != ("visual" in bones):
            raise ValueError("Pole Visual is a structural creation option; cannot change it with a numerical update")
        if align_upper_x:
            settings.pole_direction_mode = "UPPER_X"
        head, distance = pole_position(obj, settings, bones)
        length = positive(settings.pole_length, "Pole Length")
        axis, roll_axis = pole_axes(obj)
        pole_name = bones["pole"].name
        tx.watch_structure()
        # This explicit update reapplies the requested world Y / +Z frame too.
        # Ordinary Create/Load never reset a manually edited existing Pole.
        with edit_active_armature(context, obj) as edits:
            pole = edits[pole_name]
            pole.head, pole.tail = head, head + axis * length
            pole.align_roll(roll_axis)
        rec["control_options"].update(distance=distance, flip=settings.flip_direction, length=length,
                                      direction_mode=settings.pole_direction_mode, direction=list(settings.pole_direction), orientation="WORLD_Y_POS_Z")
        rec.pop("calibration", None)
        save_records(obj.data, records)
    return result(updated=1, details="Pole placement/length explicitly reapplied; axis is world +Y, Roll reference is world +Z. Existing Pole identity/constraints retained. Run Match Rest Bend again after repositioning.")


def align_pole(context):
    return update_controls(context, align_upper_x=True)


def check_instance(context):
    with operation(context) as (obj, settings, records, tx):
        rec = active_record(settings, records)
        audit(obj, rec)
        sync_instances(obj.data, records)
    return result(skipped=sum(rec["steps"]), details="All completed stages verified. Generated rest geometry and root parents may be edited; input rest geometry, managed constraints and driven properties are checked.")


class OZO_PG_arm_instance(bpy.types.PropertyGroup):
    uid: StringProperty()


class OZO_PG_arm(bpy.types.PropertyGroup):
    active_id: StringProperty(options={"HIDDEN"})
    instance: StringProperty(name="Arm Instance")
    instances: CollectionProperty(type=OZO_PG_arm_instance)
    parent_mode: EnumProperty(name="Switch Root Parent", items=(
        ("INHERIT", "Arm Tweak Previous Parent", "Read before parenting Tweaks"),
        ("BONE", "Specify Bone", "Explicit Keep Offset parent"), ("NONE", "None", "Unparented")), default="INHERIT")
    switch_parent: StringProperty(name="Parent")
    switch_parent_id: StringProperty()
    switch_parent_label: StringProperty()
    root: StringProperty(name="Root", description="Empty: find unique case-insensitive ROOT")
    pole_distance: FloatProperty(name="Distance", default=0, min=0, subtype="DISTANCE",
                                 description="Armature-space distance; 0 means current upper arm length")
    pole_length: FloatProperty(name="Pole Length", default=0.3, min=0.00002, subtype="DISTANCE")
    flip_direction: BoolProperty(name="Flip Direction")
    pole_direction_mode: EnumProperty(name="Pole Position", items=(
        ("UPPER_X", "Upper Arm Local X", "Upper arm tail offset along its local X; equivalent to a translated upper-arm locator"),
        ("REST", "Rest Bend", "Elbow outward from the rest bend plane"),
        ("EXPLICIT", "Explicit Direction", "Armature-space direction; permits straight rest chains")), default="UPPER_X")
    pole_direction: FloatVectorProperty(name="Direction", default=(0, 0, 1), size=3,
                                       description="Explicit armature-space Pole positioning direction")
    create_visual: BoolProperty(name="Create Pole Visual", default=True)
    bend_axis: EnumProperty(name="Elbow Bend Axis", description="Elbow rotation axis only; the shoulder retains XYZ IK rotation", items=(
        ("NONE", "Choose Axis", "An explicit choice is required"),
        ("X", "Local X", ""), ("Y", "Local Y", ""), ("Z", "Local Z", "")), default="NONE")
    enable_stretch: BoolProperty(name="Enable Stretch", default=True,
                                 description="Native elastic IK: permits shortening as well as lengthening. Disable for fixed bone lengths")
    arm_stretch: FloatProperty(name="Arm IK Stretch", default=0.01, min=0, max=1, precision=4)
    forearm_stretch: FloatProperty(name="Forearm IK Stretch", default=0.01, min=0, max=1, precision=4)
    pole_angle: FloatProperty(name="Pole Angle", default=0, min=-math.pi, max=math.pi, subtype="ANGLE")
    property_bone: StringProperty(name="Property Bone", default="Properties")
    property_bone_id: StringProperty()
    property_bone_label: StringProperty()
    property_mode: EnumProperty(name="Property", items=(("NEW", "New", ""), ("EXISTING", "Existing", "")), default="NEW")
    property_name: StringProperty(name="Name", description="Empty: Arm_FK_IK plus recorded .L/.R suffix")
    confirm_semantics: BoolProperty(name="0 = FK, 1 = IK", description="Explicitly confirm the semantics of the existing integer property")
    show_mapping: BoolProperty(name="Role Mapping", default=True)
    last_status: StringProperty()
    last_details: StringProperty()


for _field in INPUTS:
    for _suffix in ("", "_id", "_label"):
        OZO_PG_arm.__annotations__[_field + _suffix] = StringProperty(name=_field.replace("_", " ").title())
for _group in ("switch", "fk", "ik", "control"):
    OZO_PG_arm.__annotations__[_group + "_use_collection"] = BoolProperty(name="Specify Collection")
    OZO_PG_arm.__annotations__[_group + "_collection"] = StringProperty(name="Collection")
for _step in range(5):
    OZO_PG_arm.__annotations__["show_step_" + str(_step)] = BoolProperty(default=_step == 0)


class ArmOperator:
    bl_options = {"REGISTER", "UNDO"}
    bl_translation_context = "OZO_Tools"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        eligible = bool(obj and obj.type == "ARMATURE" and obj.mode in {"EDIT", "POSE"}
                        and obj.is_editable and obj.data.is_editable and not obj.library and not obj.data.library
                        and not obj.override_library and not obj.data.override_library and obj.data.users == 1)
        if not eligible:
            cls.poll_message_set("Use an active local editable single-user armature in Edit or Pose Mode")
        return eligible

    def execute(self, context):
        settings = context.active_object.data.ozo_arm
        try:
            output = self.run(context)
        except Exception as error:
            settings.last_status = "Conflicts: 1 | Rolled back"
            settings.last_details = str(error)
            print("[OZO Arm]", settings.last_status, str(error))
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        settings.last_status, settings.last_details = output["status"], output["details"]
        print("[OZO Arm]", output["status"], output["details"], sep="\n")
        self.report({"INFO"}, output["status"])
        return {"FINISHED"}


_OPERATIONS = (
    ("switch", "Create Switch Chain", create_switch),
    ("chains", "Create FK / IK Chains", create_chains),
    ("controls", "Create IK Controls", create_controls),
    ("connect_ik", "Connect IK", connect_ik),
    ("update_ik", "Update IK Parameters", update_ik),
    ("repair_ik", "Sync / Repair IK Setup", repair_ik),
    ("match_bend", "Match Rest Bend", match_rest_bend),
    ("connect_switch", "Connect IK/FK Switch", connect_switch),
    ("update_controls", "Update Pole Placement / Length", update_controls),
    ("align_pole", "Align Pole: Upper Arm X", align_pole),
    ("load_tweak", "Load Tweak Mapping", load_tweak_mapping),
    ("new_mapping", "New Arm Mapping", new_mapping),
    ("load_instance", "Load Arm Instance", load_instance),
    ("check", "Check Arm Instance", check_instance),
)
OPERATOR_CLASSES = tuple(type("OZO_OT_arm_" + key, (ArmOperator, bpy.types.Operator),
                              {"bl_idname": "ozo.arm_" + key, "bl_label": label, "run": staticmethod(fn)})
                         for key, label, fn in _OPERATIONS)


class OZO_OT_arm_report(bpy.types.Operator):
    bl_idname = "ozo.arm_report"
    bl_label = "Arm Details"

    def execute(self, context):
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=700)

    def draw(self, context):
        import textwrap
        settings = context.active_object.data.ozo_arm
        for line in [settings.last_status] + settings.last_details.splitlines():
            for wrapped in textwrap.wrap(line, width=95):
                self.layout.label(text=wrapped, translate=False)


def collection_ui(layout, obj, settings, group, label=""):
    if label:
        layout.label(text=label, translate=False)
    layout.prop(settings, group + "_use_collection", translate=False)
    if getattr(settings, group + "_use_collection"):
        layout.prop_search(settings, group + "_collection", obj.data, "collections_all", text="Collection", translate=False)
    else:
        active = obj.data.collections.active
        layout.label(text="Active: " + (active.name if active else "None"), translate=False)


class OZO_PT_arm(bpy.types.Panel):
    bl_idname = "OZO_PT_arm"
    bl_label = "Arm"
    bl_parent_id = "OZO_PT_bone_controls"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OZO_Tools"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 3

    def draw(self, context):
        outer = self.layout.row()
        outer.column().ui_units_x = 1.0
        layout = outer.column()
        layout.use_property_decorate = False
        obj = context.active_object
        if not obj or obj.type != "ARMATURE":
            layout.label(text="Select an armature.", translate=False)
            return
        settings = obj.data.ozo_arm
        layout.operator("ozo.arm_new_mapping", translate=False)
        layout.label(text="Arm Instance", translate=False)
        layout.prop_search(settings, "instance", settings, "instances", text="", translate=False)
        row = layout.row(align=True)
        row.operator("ozo.arm_load_instance", text="Load", translate=False)
        row.operator("ozo.arm_check", text="Check", translate=False)
        rec, error, pending = None, "", set()
        try:
            records = read_records(obj.data)
            rec = records["arms"].get(settings.active_id)
            if rec and obj.mode != "EDIT":
                active_record(settings, records)
                audit(obj, rec)
            if rec and rec["steps"][2] and obj.mode != "EDIT":
                applied = rec["control_options"]
                distance = settings.pole_distance or resolved(obj, rec)["ik_arm"].length
                if (abs(distance - applied["distance"]) > rig.EPSILON or abs(settings.pole_length - applied["length"]) > rig.EPSILON
                        or settings.flip_direction != applied["flip"] or settings.create_visual != applied["visual"]
                        or settings.pole_direction_mode != applied["direction_mode"] or list(settings.pole_direction) != applied["direction"]):
                    pending.add(2)
            if rec and rec["steps"][3]:
                if (ik_options(settings) != rec["options"] or settings.enable_stretch != rec["ik_parameters"]["enable_stretch"]
                        or abs(settings.pole_angle - rec["ik_parameters"]["pole_angle"]) > 1e-6):
                    pending.add(3)
        except (ValueError, KeyError, TypeError) as exc:
            error = str(exc)
        layout.prop(settings, "show_mapping", translate=False)
        if settings.show_mapping:
            box = layout.box()
            box.operator("ozo.arm_load_tweak", translate=False)
            for role in ROLES:
                box.label(text=role.title(), translate=False)
                for prefix, label in (("source_", "ORG"), ("tweak_", "Tweak")):
                    field = prefix + role
                    box.prop_search(settings, field, obj.data, "bones", text=label, translate=False)
            box.label(text="Hand Tip Tweak", translate=False)
            box.prop_search(settings, "tip", obj.data, "bones", text="", translate=False)
        if error:
            layout.label(text="Needs inspection (see Check / Details)", icon="ERROR", translate=False)
        if obj.mode == "EDIT" and rec:
            layout.label(text="Edit Mode: Check to verify current edits", translate=False)
        stages = (("switch", "Create Switch Chain"), ("chains", "Create FK / IK Chains"),
                  ("controls", "Create IK Controls"), ("connect_ik", "Connect IK"),
                  ("connect_switch", "Connect IK/FK Switch"))
        for i, (key, label) in enumerate(stages):
            box = layout.box()
            done = rec and rec["steps"][i]
            state = "Needs inspection" if done and error else "Pending explicit update" if i in pending else "Complete" if done else "Not complete"
            expanded = getattr(settings, "show_step_" + str(i))
            box.prop(settings, "show_step_" + str(i), text=f"{i+1}. {label}",
                     icon="TRIA_DOWN" if expanded else "TRIA_RIGHT", emboss=False, translate=False)
            box.label(text=state, icon="ERROR" if done and error else "CHECKMARK" if done else "RADIOBUT_OFF", translate=False)
            if not expanded:
                continue
            if i == 0:
                box.label(text="Switch Root Parent", translate=False)
                box.prop(settings, "parent_mode", text="", translate=False)
                if settings.parent_mode == "BONE":
                    box.prop_search(settings, "switch_parent", obj.data, "bones", text="Parent", translate=False)
                collection_ui(box, obj, settings, "switch")
            elif i == 1:
                collection_ui(box, obj, settings, "fk", "FK")
                collection_ui(box, obj, settings, "ik", "IK")
            elif i == 2:
                box.prop_search(settings, "root", obj.data, "bones", translate=False)
                box.prop(settings, "pole_direction_mode", translate=False)
                box.label(text="Pole axis: World +Y / Roll: +Z", translate=False)
                if settings.pole_direction_mode == "EXPLICIT":
                    box.prop(settings, "pole_direction", translate=False)
                box.prop(settings, "pole_distance", translate=False)
                if settings.pole_distance == 0:
                    box.label(text="Distance 0 = upper arm length", translate=False)
                for field in ("flip_direction", "pole_length", "create_visual"):
                    box.prop(settings, field, translate=False)
                collection_ui(box, obj, settings, "control")
            elif i == 3:
                box.label(text="Elbow Bend Axis", translate=False)
                box.prop(settings, "bend_axis", text="", translate=False)
                box.label(text="Shoulder: XYZ rotation free", translate=False)
                for field in ("enable_stretch", "arm_stretch", "forearm_stretch", "pole_angle"):
                    box.prop(settings, field, translate=False)
                if settings.enable_stretch:
                    box.label(text="Elastic IK can shorten bone lengths", translate=False)
            elif i == 4:
                box.label(text="Property Bone", translate=False)
                box.prop_search(settings, "property_bone", obj.data, "bones", text="", translate=False)
                box.prop(settings, "property_mode", translate=False)
                box.prop(settings, "property_name", translate=False)
                default = "Arm_FK_IK" + (rec["side"] if rec else "")
                if not settings.property_name:
                    box.label(text="Name: " + default, translate=False)
                if settings.property_mode == "EXISTING":
                    box.prop(settings, "confirm_semantics", translate=False)
                box.label(text="0 = FK     1 = IK", translate=False)
                if rec and rec["link"]:
                    index = {b.get(rig.BONE_ID): b for b in obj.data.bones}
                    holder = index.get(rec["link"]["bone"])
                    if holder and rec["link"]["name"] in obj.pose.bones[holder.name]:
                        box.prop(obj.pose.bones[holder.name], '["' + bpy.utils.escape_identifier(rec["link"]["name"]) + '"]', text="FK / IK")
            box.operator("ozo.arm_" + key, text=label, translate=False)
            if i == 2 and done:
                box.operator("ozo.arm_align_pole", translate=False)
                box.operator("ozo.arm_update_controls", translate=False)
            if i == 3:
                box.operator("ozo.arm_update_ik", translate=False)
                box.operator("ozo.arm_repair_ik", translate=False)
                box.operator("ozo.arm_match_bend", translate=False)
        if settings.last_status:
            layout.operator("ozo.arm_report", text="Last Operation Details", translate=False)


CLASSES = (OZO_PG_arm_instance, OZO_PG_arm) + OPERATOR_CLASSES + (OZO_OT_arm_report, OZO_PT_arm)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Armature.ozo_arm = PointerProperty(type=OZO_PG_arm)


def unregister():
    del bpy.types.Armature.ozo_arm
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
