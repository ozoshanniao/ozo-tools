# SPDX-License-Identifier: GPL-3.0-or-later
"""ROOT-parented rotation-isolating socket mechanisms at an active bone head."""

import math
import re

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, PointerProperty, StringProperty
from mathutils import Vector

from .bone_controls import ControlsOperator, destination, validate_names
from .bone_parenting import edit_active_armature

AXES = {
    "POS_Z": (0, 0, 1), "POS_Y": (0, 1, 0), "POS_X": (1, 0, 0),
    "NEG_Z": (0, 0, -1), "NEG_Y": (0, -1, 0), "NEG_X": (-1, 0, 0),
}


def active_source(context):
    obj = context.active_object
    if obj.mode == "EDIT":
        bone = obj.data.edit_bones.active
        if bone is None or not (bone.select or bone.select_head) or bone.hide:
            raise ValueError("Select an active source bone or its head in Edit Mode")
    else:
        pose = context.active_pose_bone
        if pose is None or pose.id_data != obj or not pose.select:
            raise ValueError("Select an active source bone in Pose Mode")
        bone = pose.bone
    return bone


def socket_base(name):
    # Preserve the actual controller name, including an optional ORG marker.
    name = re.sub(r"(?:\.\d{3,})+$", "", name.strip())
    side = name[-2:] if name.endswith((".L", ".R")) else ""
    stem = re.sub(r"(?:\.\d{3,})+$", "", name[:-2] if side else name).strip()
    if not stem:
        raise ValueError("Source has no usable controller name")
    return stem + side


def socket_plan(context):
    obj = context.active_object
    data = obj.data
    settings = data.ozo_bone_socket
    source = active_source(context)
    bones = data.edit_bones if obj.mode == "EDIT" else data.bones
    if source.name.startswith(("MCH_Socket_", "MCH_INT_Socket_")):
        raise ValueError("Select the original controller, not an existing Socket mechanism")
    if settings.root_bone:
        root = bones.get(settings.root_bone)
        if root is None:
            raise ValueError(f"Root bone not found: {settings.root_bone}")
    else:
        roots = [bone for bone in bones if bone.name.casefold() == "root"]
        if len(roots) != 1:
            raise ValueError("Choose a Root bone; automatic lookup needs exactly one ROOT/root/Root")
        root = roots[0]
    ancestor = root
    while ancestor:
        if ancestor == source:
            raise ValueError("Source cannot be Root or an ancestor of Root")
        ancestor = ancestor.parent
    lengths = settings.socket_length, settings.int_length
    if any(not math.isfinite(value) or value <= 0 for value in lengths):
        raise ValueError("Socket and INT lengths must be positive")
    collection = destination(data, settings.use_collection, settings.collection)
    base = socket_base(source.name)
    names = "MCH_Socket_" + base, "MCH_INT_Socket_" + base
    validate_names(data, names)
    linear = obj.matrix_world.to_3x3()
    try:
        inverse = linear.inverted()
    except ValueError:
        raise ValueError("Armature world transform is singular; cannot determine a world direction") from None
    world_y = Vector(AXES[settings.direction])
    # Bone Y is its head-to-tail axis. Fix roll against world Z, using -Y for
    # vertical bones to match the reference file's +Z orientation exactly.
    world_z = Vector((0, 0, 1)) if abs(world_y.z) < 0.5 else Vector((0, -1, 0))
    local_y = (inverse @ world_y).normalized()
    local_z = (inverse @ world_z).normalized()
    head = (source.head if obj.mode == "EDIT" else source.head_local).copy()
    return {"source": source.name, "root": root.name, "names": names,
            "parent": source.parent.name if source.parent else None,
            "head": head, "axis": local_y, "roll_axis": local_z,
            "lengths": lengths, "collection": collection,
            "rotation_follow": settings.rotation_follow}


def make_socket_bone(bones, name, plan, length):
    bone = bones.new(name)
    if bone.name != name:
        raise ValueError(f"Could not create exact bone name: {name}")
    bone.head = plan["head"]
    bone.tail = bone.head + plan["axis"] * length
    bone.align_roll(plan["roll_axis"])
    bone.use_connect = False
    bone.use_deform = False
    bone.select = bone.select_head = bone.select_tail = False
    for collection in list(bone.collections):
        collection.unassign(bone)
    plan["collection"].assign(bone)
    return bone


def add_socket_constraints(obj, plan):
    pose = obj.pose.bones[plan["names"][1]]
    for kind in ("COPY_LOCATION", "COPY_SCALE", "COPY_ROTATION"):
        constraint = pose.constraints.new(kind)
        constraint.target = obj
        constraint.subtarget = plan["names"][0]
        constraint.target_space = constraint.owner_space = "WORLD"
        constraint.influence = plan["rotation_follow"] if kind == "COPY_ROTATION" else 1.0


def create_socket(context):
    plan = socket_plan(context)
    obj = context.active_object
    created = []
    state = None
    try:
        with edit_active_armature(context, obj) as bones:
            source = bones[plan["source"]]
            state = (source.parent.name if source.parent else None, source.use_connect,
                     source.head.copy(), source.tail.copy(), source.roll)
            for name, length in zip(plan["names"], plan["lengths"]):
                created.append(name)
                make_socket_bone(bones, name, plan, length)
            # Socket takes the source's previous parent with Keep Offset.
            outer = bones[plan["names"][0]]
            outer.parent = bones[plan["parent"]] if plan["parent"] else None
            intermediate = bones[plan["names"][1]]
            intermediate.parent = bones[plan["root"]]
            source.use_connect = False
            source.parent = intermediate
        mode = obj.mode
        if mode == "EDIT":
            bpy.ops.object.mode_set(mode="OBJECT")
        try:
            add_socket_constraints(obj, plan)
            context.view_layer.update()
        finally:
            if mode == "EDIT":
                bpy.ops.object.mode_set(mode="EDIT")
    except Exception:
        with edit_active_armature(context, obj) as bones:
            if state is not None:
                source = bones[plan["source"]]
                source.use_connect = False
                source.parent = bones.get(state[0]) if state[0] else None
                source.head, source.tail, source.roll = state[2:]
                source.use_connect = state[1]
            for name in reversed(created):
                if name in bones:
                    bones.remove(bones[name])
        raise
    return 2


class OZO_PG_bone_socket(bpy.types.PropertyGroup):
    direction: EnumProperty(name="World Direction", default="POS_Z", items=(
        ("POS_Z", "+Z (Up)", "Point toward world +Z"),
        ("POS_Y", "+Y (Back)", "Point toward world +Y"),
        ("POS_X", "+X (Right)", "Point toward world +X"),
        ("NEG_Z", "-Z (Down)", "Point toward world -Z"),
        ("NEG_Y", "-Y (Front)", "Point toward world -Y"),
        ("NEG_X", "-X (Left)", "Point toward world -X"),
    ))
    socket_length: FloatProperty(name="Socket Length", default=1.0, min=0.00001,
                                precision=4, subtype="DISTANCE", unit="LENGTH")
    int_length: FloatProperty(name="INT Length", default=0.5, min=0.00001,
                             precision=4, subtype="DISTANCE", unit="LENGTH")
    root_bone: StringProperty(name="Root", description="Leave empty to auto-detect ROOT, root or Root")
    rotation_follow: FloatProperty(name="Rotation Follow", default=1.0, min=0.0, max=1.0,
                                  description="Initial Copy Rotation influence: 0 isolates Socket rotation, 1 follows it")
    use_collection: BoolProperty(name="Specify Collection", default=False)
    collection: StringProperty(name="Collection", description="Existing collection for both Socket bones")
    last_status: StringProperty(options={"SKIP_SAVE"})


class OZO_OT_create_socket(ControlsOperator, bpy.types.Operator):
    bl_idname = "ozo.create_socket"
    bl_label = "Create MCH Socket"
    bl_description = "Create Socket and ROOT-parented INT at the active source's rest head; parent source to INT"
    kind = "Socket"
    run = staticmethod(create_socket)

    def execute(self, context):
        try:
            self.run(context)
        except (ValueError, RuntimeError, TypeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        message = "Created Socket + INT"
        context.active_object.data.ozo_bone_socket.last_status = message
        self.report({"INFO"}, message)
        return {"FINISHED"}


def draw_socket(layout, context):
    obj = context.active_object
    settings = obj.data.ozo_bone_socket
    box = layout
    try:
        name = active_source(context).name
    except ValueError:
        name = "Select a source bone"
    box.label(text="Active: " + name, translate=False)
    box.prop(settings, "direction", text="World Axis", translate=False)
    box.prop(settings, "socket_length", text="Socket Length", translate=False)
    box.prop(settings, "int_length", text="INT Length", translate=False)
    box.prop_search(settings, "root_bone", obj.data, "bones", text="Root", translate=False)
    if not settings.root_bone:
        bones = obj.data.edit_bones if obj.mode == "EDIT" else obj.data.bones
        roots = [b.name for b in bones if b.name.casefold() == "root"]
        box.label(text="Auto Root: " + (roots[0] if len(roots) == 1 else "Choose Root"), translate=False)
    box.prop(settings, "rotation_follow", text="Rotation Follow", translate=False)
    box.prop(settings, "use_collection", text="Specify Collection", translate=False)
    if settings.use_collection:
        box.prop_search(settings, "collection", obj.data, "collections_all", text="Collection", translate=False)
    else:
        active = obj.data.collections.active
        box.label(text="Active Collection: " + (active.name if active else "None"), translate=False)
    box.operator("ozo.create_socket", text="Create MCH Socket", translate=False)
    if settings.last_status:
        box.label(text=settings.last_status, translate=False)


class OZO_PT_bone_socket(bpy.types.Panel):
    bl_idname = "OZO_PT_bone_socket"
    bl_label = "MCH Socket"
    bl_translation_context = "OZO_Tools"
    bl_parent_id = "OZO_PT_bone_controls"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "OZO_Tools"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 1

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
        draw_socket(layout, context)


CLASSES = (OZO_PG_bone_socket, OZO_OT_create_socket, OZO_PT_bone_socket)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Armature.ozo_bone_socket = PointerProperty(type=OZO_PG_bone_socket)


def unregister():
    del bpy.types.Armature.ozo_bone_socket
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
