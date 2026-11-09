# SPDX-License-Identifier: GPL-3.0-or-later
"""OZO_Tools: modular Blender tools."""

bl_info = {
    "name": "OZO_Tools",
    "author": "OZO",
    "version": (0, 10, 6),
    "blender": (5, 2, 0),
    "location": "3D View > Sidebar > OZO_Tools",
    "description": "Rigging tools for constraints, parenting, controls, staged Arm, rotation follow and animation scale",
    "category": "Rigging",
}

from . import bone_constraints, bone_deform, bone_parenting, bone_controls, bone_socket, animation_scale, rotation_follow, arm, bone_identity

MODULES = (bone_constraints, bone_deform, bone_parenting, bone_controls, bone_socket, animation_scale, rotation_follow, arm, bone_identity)


def register():
    for module in MODULES:
        module.register()


def unregister():
    for module in reversed(MODULES):
        module.unregister()
