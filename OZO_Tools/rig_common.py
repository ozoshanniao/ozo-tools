# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared identity, context, transaction and clean MCH-parent primitives.

No standalone tool is registered here. Existing Tweak/Socket records are untouched.
"""
from contextlib import contextmanager
import math
import re
import uuid

import bpy

from .bone_parenting import edit_active_armature

BONE_ID = "ozo_rig_identity"
EPSILON = 1e-5
FRAME_ROUNDOFF = 5e-5  # Near-unit rest-basis drift, not a position/length tolerance.


def require_rig(context):
    obj = context.active_object
    if not obj or obj.type != "ARMATURE" or obj.mode not in {"EDIT", "POSE"}:
        raise ValueError("Select bones in Armature Edit or Pose Mode")
    if (not obj.is_editable or not obj.data.is_editable or obj.library or obj.data.library
            or obj.override_library or obj.data.override_library):
        raise ValueError("Use a local editable armature without a library override")
    if obj.data.users != 1:
        raise ValueError("Make armature data single-user before building Rotation Follow")
    if not all(math.isfinite(x) for row in obj.matrix_world for x in row) or abs(obj.matrix_world.to_3x3().determinant()) < 1e-9:
        raise ValueError("Armature world transform is singular or non-finite")
    return obj


@contextmanager
def object_context(context):
    """Synchronize EditBones and restore selection on every originally selected rig."""
    obj = context.active_object
    mode = obj.mode
    objects = list(context.selected_objects)
    states = []
    for other in objects:
        if other.type != "ARMATURE":
            continue
        if other.mode == "EDIT":
            bones = other.data.edit_bones
            states.append((other, True, bones.active.name if bones.active else None,
                           {b.name: (b.select, b.select_head, b.select_tail) for b in bones}))
        else:
            states.append((other, False, other.data.bones.active.name if other.data.bones.active else None,
                           {p.name: p.select for p in other.pose.bones}))
    try:
        if mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for other in objects:
            if other != obj:
                other.select_set(False)
        yield obj
    finally:
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        context.view_layer.objects.active = obj
        for other in objects:
            other.select_set(True)
        if mode != "OBJECT":
            bpy.ops.object.mode_set(mode=mode)
        for other, editing, active, selected in states:
            if editing:
                bones = other.data.edit_bones
                for b in bones:
                    b.select, b.select_head, b.select_tail = selected.get(b.name, (False, False, False))
                bones.active = bones.get(active) if active else None
            else:
                for p in other.pose.bones:
                    p.select = selected.get(p.name, False)
                other.data.bones.active = other.data.bones.get(active) if active else None


def identity(bone):
    value = bone.get(BONE_ID)
    if not value:
        value = uuid.uuid4().hex
        bone[BONE_ID] = value
    return value


def index_bones(data):
    result = {}
    for bone in data.bones:
        value = bone.get(BONE_ID)
        if value:
            if value in result:
                raise ValueError(f"Duplicated rig identity: {result[value].name}, {bone.name}; use RIG Tools > Bone Identity > Repair Duplicate IDs")
            result[value] = bone
    return result


def resolve(index, value, label):
    if value not in index:
        raise ValueError(f"Missing or replaced {label}; restore the original bone (a reused name is not its identity)")
    return index[value]


def rest_geometry(bone):
    return {"matrix": [list(row) for row in bone.matrix_local], "length": bone.length}


def _rest_axes(matrix):
    """Normalize only near-rigid rest frames; reject scale/shear/corrupt frames."""
    if not all(math.isfinite(matrix[i][j]) for i in range(4) for j in range(4)):
        return None
    if max(abs(matrix[3][i] - (1.0 if i == 3 else 0.0)) for i in range(4)) > EPSILON:
        return None
    axes = []
    for j in range(3):
        axis = tuple(matrix[i][j] for i in range(3))
        length = math.sqrt(sum(value * value for value in axis))
        if abs(length - 1.0) > FRAME_ROUNDOFF:
            return None
        axes.append(tuple(value / length for value in axis))
    if any(abs(sum(a * b for a, b in zip(axes[i], axes[j]))) > FRAME_ROUNDOFF
           for i, j in ((0, 1), (0, 2), (1, 2))):
        return None
    x, y, z = axes
    handedness = ((x[1] * y[2] - x[2] * y[1]) * z[0]
                  + (x[2] * y[0] - x[0] * y[2]) * z[1]
                  + (x[0] * y[1] - x[1] * y[0]) * z[2])
    if handedness < 1.0 - FRAME_ROUNDOFF:
        return None
    return axes


def same_geometry(bone, saved):
    # Edit Mode round-trips can change tiny per-column normalization errors in
    # imported Bone.matrix_local, while head, length and orientation stay fixed.
    # Compare those geometric quantities separately instead of raw matrix cells.
    current, original = bone.matrix_local, saved["matrix"]
    if not math.isfinite(bone.length) or not math.isfinite(saved["length"]):
        return False
    if abs(bone.length - saved["length"]) > EPSILON:
        return False
    a, b = _rest_axes(current), _rest_axes(original)
    if a is None or b is None:
        return False
    head_error = math.sqrt(sum((bone.head_local[i] - original[i][3]) ** 2 for i in range(3)))
    return head_error <= EPSILON and all(
        math.sqrt(sum((x - y) ** 2 for x, y in zip(axis_a, axis_b))) <= EPSILON
        for axis_a, axis_b in zip(a, b))


def clean_base(name):
    name = re.sub(r"(?:\.\d{3,})+$", "", name.strip())
    side = name[-2:] if name.endswith((".L", ".R")) else ""
    stem = re.sub(r"(?:\.\d{3,})+$", "", name[:-2] if side else name).strip()
    if not stem:
        raise ValueError(f"No usable mechanism base name: {name}")
    return stem + side


def insert_mch_parents(context, specifications, collection, transaction):
    """Insert clean Keep Offset parents; callers prevalidate all names and mappings."""
    obj = context.active_object
    transaction.watch_structure()
    with edit_active_armature(context, obj) as bones:
        for spec in specifications:
            name = spec["mch_name"]
            transaction.created_bones.append(name)
            controlled = bones[spec["controlled_name"]]
            parent = controlled.parent
            head, tail, roll = controlled.head.copy(), controlled.tail.copy(), controlled.roll
            mch = bones.new(name)
            if mch.name != name:
                raise ValueError(f"Could not create exact mechanism name: {name}")
            mch.head, mch.tail, mch.roll = head, tail, roll
            mch.length = spec["length"]
            mch.parent = parent
            mch.use_connect = False
            mch.use_deform = False
            mch[BONE_ID] = spec["mch_id"]
            mch.select = mch.select_head = mch.select_tail = False
            for old in list(mch.collections):
                old.unassign(mch)
            collection.assign(mch)
            controlled.use_connect = False
            controlled.parent = mch
            controlled.head, controlled.tail, controlled.roll = head, tail, roll


def animation_curves(obj, drivers=True):
    anim = obj.animation_data
    if not anim:
        return []
    curves = list(anim.drivers) if drivers else []
    actions = {anim.action} if anim.action else set()
    def visit(strips):
        for strip in strips:
            if strip.action:
                actions.add(strip.action)
            if strip.type == "META":
                visit(strip.strips)
    for track in anim.nla_tracks:
        visit(track.strips)
    for action in actions:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in getattr(strip, "channelbags", []):
                    curves.extend(bag.fcurves)
    return curves


def driver_for(obj, path):
    if obj.animation_data:
        return next((c for c in obj.animation_data.drivers if c.data_path == path), None)
    return None


def driver_state(curve):
    if curve is None:
        return None
    driver = curve.driver
    variables = []
    for variable in driver.variables:
        variables.append({"name": variable.name, "type": variable.type, "targets": [
            {key: getattr(t, key) for key in ("id_type", "id", "data_path", "bone_target", "transform_type", "transform_space", "rotation_mode")}
            for t in variable.targets]})
    return {"type": driver.type, "expression": driver.expression, "use_self": driver.use_self,
            "variables": variables, "mute": curve.mute, "modifiers": len(curve.modifiers)}


def transform_dependencies(driver, obj):
    names = set()
    for variable in driver.variables:
        for target in variable.targets:
            if target.id != obj:
                continue
            if variable.type == "TRANSFORMS" and target.bone_target:
                names.add(target.bone_target)
            elif variable.type == "SINGLE_PROP":
                match = re.match(r'pose\.bones\["((?:[^"\\]|\\.)*)"\]\.(?:location|scale|rotation_\w+|matrix\w*)', target.data_path)
                if match:
                    names.add(bpy.utils.unescape_identifier(match.group(1)))
    return names


def restore_driver(owner, state):
    if state is None:
        if driver_for(owner.id_data, owner.path_from_id("influence")):
            owner.driver_remove("influence")
        return
    curve = owner.driver_add("influence")
    curve.mute = state["mute"]
    driver = curve.driver
    driver.type, driver.use_self = state["type"], state["use_self"]
    for variable in list(driver.variables):
        driver.variables.remove(variable)
    for saved in state["variables"]:
        variable = driver.variables.new()
        variable.name, variable.type = saved["name"], saved["type"]
        for target, fields in zip(variable.targets, saved["targets"]):
            # id_type must precede id; transform settings are irrelevant for SINGLE_PROP.
            target.id_type = fields["id_type"]
            target.id = fields["id"]
            for key, value in fields.items():
                if key not in {"id_type", "id"}:
                    setattr(target, key, value)
    driver.expression = state["expression"]


ROTATION_FIELDS = ("target", "subtarget", "target_space", "owner_space", "mix_mode",
                   "use_x", "use_y", "use_z", "invert_x", "invert_y", "invert_z", "mute", "influence")


class RigTransaction:
    """Only roll back our own touched records, constraints, drivers, properties and MCHs."""
    def __init__(self, context, record_key):
        self.context, self.obj, self.record_key = context, context.active_object, record_key
        self.raw = self.obj.data.get(record_key)
        self.ids = {b.name: b.get(BONE_ID) for b in self.obj.data.bones}
        self.created_bones, self.created_constraints, self.constraints, self.properties = [], [], [], []
        self.structure = None

    def __enter__(self):
        return self

    def watch_structure(self):
        if self.structure is None:
            with edit_active_armature(self.context, self.obj) as bones:
                self.structure = {b.name: (b.parent.name if b.parent else None, b.use_connect,
                                          b.head.copy(), b.tail.copy(), b.roll) for b in bones}

    def watch_constraint(self, pose, constraint):
        self.constraints.append((pose.name, constraint.name,
            {key: getattr(constraint, key) for key in ROTATION_FIELDS},
            list(pose.constraints).index(constraint),
            driver_state(driver_for(self.obj, constraint.path_from_id("influence")))))

    def new_constraint(self, pose):
        constraint = pose.constraints.new("COPY_ROTATION")
        self.created_constraints.append((pose.name, constraint))
        return constraint

    def new_property(self, pose, key):
        self.properties.append((pose.name, key))

    def __exit__(self, kind, error, traceback):
        if kind is None:
            return False
        for name, constraint in reversed(self.created_constraints):
            if driver_for(self.obj, constraint.path_from_id("influence")):
                constraint.driver_remove("influence")
            self.obj.pose.bones[name].constraints.remove(constraint)
        for name, cname, fields, order, driver in reversed(self.constraints):
            pose = self.obj.pose.bones[name]
            constraint = pose.constraints[cname]
            restore_driver(constraint, driver)
            for key, value in fields.items():
                setattr(constraint, key, value)
            pose.constraints.move(list(pose.constraints).index(constraint), order)
        for name, key in reversed(self.properties):
            pose = self.obj.pose.bones[name]
            if key in pose:
                del pose[key]
        if self.structure is not None:
            with edit_active_armature(self.context, self.obj) as bones:
                for b in bones:
                    b.use_connect = False
                for name, state in self.structure.items():
                    bones[name].parent = bones.get(state[0]) if state[0] else None
                for name in reversed(self.created_bones):
                    if name in bones:
                        bones.remove(bones[name])
                for name, state in self.structure.items():
                    b = bones[name]
                    b.head, b.tail, b.roll = state[2:]
                    b.use_connect = state[1]
        for name, value in self.ids.items():
            bone = self.obj.data.bones[name]
            if value is None:
                if BONE_ID in bone:
                    del bone[BONE_ID]
            else:
                bone[BONE_ID] = value
        if self.raw is None:
            if self.record_key in self.obj.data:
                del self.obj.data[self.record_key]
        else:
            self.obj.data[self.record_key] = self.raw
        self.context.view_layer.update()
        return False


def check_cycles(obj, source, owners, extra_parents=None, ignore=()):
    """Reject new obvious same-armature parent/constraint/transform-driver cycles."""
    graph = {b.name: {b.parent.name} if b.parent else set() for b in obj.data.bones}
    for pose in obj.pose.bones:
        for constraint in pose.constraints:
            if constraint.as_pointer() in ignore:
                continue
            for target, name in ((getattr(constraint, "target", None), getattr(constraint, "subtarget", "")),
                                 (getattr(constraint, "pole_target", None), getattr(constraint, "pole_subtarget", ""))):
                if target == obj and name in graph:
                    graph[pose.name].add(name)
            for target in getattr(constraint, "targets", []):
                if target.target == obj and target.subtarget in graph:
                    graph[pose.name].add(target.subtarget)
    for curve in animation_curves(obj):
        if not getattr(curve, "driver", None):
            continue
        match = re.match(r'pose\.bones\["((?:[^"\\]|\\.)*)"\]', curve.data_path)
        if not match:
            continue
        owner = bpy.utils.unescape_identifier(match.group(1))
        if owner in graph:
            graph[owner].update(name for name in transform_dependencies(curve.driver, obj) if name in graph)
    for child, parent in (extra_parents or {}).items():
        graph[child] = {parent} if parent else set()
    for owner in owners:
        pending, visited = [source], set()
        while pending:
            current = pending.pop()
            if current == owner:
                raise ValueError(f"Rotation dependency cycle: {owner} -> {source} -> ... -> {owner}")
            if current not in visited:
                visited.add(current)
                pending.extend(graph.get(current, ()))
        graph.setdefault(owner, set()).add(source)
