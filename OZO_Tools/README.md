# OZO_Tools 0.10.6

A modular Blender tool collection. Tested with Blender 5.2.2 LTS.

## Installation

In Blender, open Edit > Preferences > Add-ons, choose Install from Disk from the menu, select `OZO_Tools-0.10.6.zip`, and enable OZO_Tools.

In the 3D View, press N and open the OZO_Tools tab. It contains two independent top-level panels: **OZO_Tools** (Copy Transform, Deform, DEF Parenting and Animation Scale) and **RIG Tools**. RIG Tools has separate **Tweak / FK**, **MCH Socket**, **Rotation Follow**, **Arm**, and **Bone Identity** subpanels, initially collapsed and independently expandable. Collapsing OZO_Tools does not hide RIG Tools.

Animation Transfer was removed in 0.6.4. Its scripts, calibration, mapping and reports are retained separately in the development workspace for the ongoing animation repair and a future skill workflow.

## Copy Transform

Enter A (constrained bone prefix) and B (source bone prefix), then click Apply. A copies transforms from B.

Matching is case-sensitive: `DEF-arm.L` maps to `ORG-arm.L`, but not `org-arm.L` or `ORG-Arm.L`. The remaining name must match exactly. Default prefixes DEF / ORG also work with hyphens or underscores. Use DEF- / ORG- to restrict matching to that separator.

All armatures in the current scene are scanned, including hidden and unselected ones. Pairing stays within each armature object. Missing targets are skipped. Empty, equal, or overlapping prefixes are rejected. Exit Armature Edit Mode before applying. Changes support Undo.

Expand Options to choose:

- **Target Space / Owner Space:** Blender's native space options, including World, Pose, Local With Parent, Local, and Custom. Target Space also includes Local Space (Owner Orientation).
- **Space Object / Space Bone:** shown when Custom Space is selected. A space object is required; the bone is optional.
- **Mix:** Replace, Before Original (Full / Aligned / Split Channels), After Original (Full / Aligned / Split Channels).
- **Influence:** 0 to 1.

Defaults are World Space for both spaces, Replace, and influence 1. Apply adds or repairs constraints to the currently selected options. These settings are stored per scene. Head/Tail is zero, B-Bone shape following is disabled, and shear removal is disabled.

Existing correct constraints retain their names and order. Recognized incorrect constraints are repaired in place. Recognized duplicates are consolidated, preferring a correct constraint. Recognition includes OZO constraint names, B-prefixed targets, missing targets, or a lone Copy Transforms constraint. Other constraint types remain intact. Multiple unrelated Copy Transforms constraints, animated/driven settings, and read-only data are reported rather than guessed or overwritten.

After applying, the panel shows a short status. Click the information button for counts and issue details; the full report is also printed to Blender's system console.

## Deform

Click Fix Deform to enable the Deform switch on every bone whose name starts with `DEF` or `ROOT`, and disable it on all other bones. Matching is case-sensitive. `DEF`, `DEF-arm`, `DEF_arm`, `ROOT`, `ROOT.001`, and `ROOT-control` must have Deform enabled. `def-arm`, `root`, and other prefixes must have it disabled.

Both incorrect enabled states and incorrect disabled states are repaired. Bones already matching the rule are skipped. All armatures in the current scene are scanned, including hidden and unselected ones. Shared armature datablocks are processed only once; their changes also affect other objects using the same datablock. Unshared armatures outside the current scene are untouched. Read-only linked armatures requiring changes are skipped and reported. Exit Armature Edit Mode before applying. Changes support Undo.

The compact result shows how many bones were enabled and disabled. Click the information button for already correct, read-only, and error counts.

## DEF Parenting

This tool operates on the active armature only. DEF matching is case-sensitive.

1. Start with the correct original hierarchy and click **Save Template**. It records every DEF bone's parent (including no parent) and Connected switch. Clicking Save Template again explicitly replaces the previous template with the current hierarchy.
2. Choose a **Root** bone from the current armature; the default is ROOT_SEC. Any existing non-DEF bone can be used, provided it does not create a cycle.
3. Click **DEF To ROOT** to parent every DEF bone directly to the chosen root, with Connected disabled.
4. Click **Restore Original** to recover the saved parents and Connected states.

Switching never saves, updates, or overwrites the template. A valid saved template is required before switching. Only Save Template replaces it. The template and selected Root live on the armature datablock and survive saving/reopening a blend file or reloading the addon. Shared armature data shares the hierarchy and template as well.

Switches preserve bone rest positions, orientations, and lengths, and leave pose transform channels and constraints alone. Actual evaluated poses and animations may change when the hierarchy or Connected state changes; this tool does not bake or compensate animations. A restore requiring a Connected head to move to a changed parent tail is rejected rather than changing rest geometry.

Use Object or Pose Mode. The previous mode, selected objects, and active object are preserved. Missing/renamed DEF bones or original parents, missing roots, cycles, or read-only data stop the operation. Undo is supported for saving and switching. The template stores names, so keep naming stable between saving and restoring.

## RIG Tools: Tweak / FK

Select source bones in Edit or Pose Mode on the active, local, single-user armature. Only the current selection on that armature is used, with no name-prefix filtering; the panel displays the selection count. A single bone, a continuous unbranched chain, or several independent chains can be processed together. Chain order follows parenting, not names or selection order. Internal gaps, branches, non-coincident joints, existing Stretch To constraints and conflicting names are rejected before editing. Bone names and source Deform flags are preserved.

1. Select the source bones and set **Tweak Length** (default 0.3). Length is a positive custom value in armature space, displayed using scene length units; 0.03 and 0.15 are supported. Object scale still scales the displayed controls. New controls retain source orientation and roll. Tweak heads stay at the ORG heads; each selected chain gets one same-length Tip control at its final ORG tail.
2. Click **Create Tweak**. Each ORG becomes the Keep Offset child of its corresponding Tweak. Its Stretch To targets the next Tweak's head, or the Tip head at the end. Constraints use Blender's native newly-created defaults, with rest length initialized from the original rest bone. Until FK is built, all Tweaks and the Tip share the original chain root's external parent (or have no parent).
3. Click **Create FK**. The original rest geometry and hierarchy are restored as new FK bones. Each Tweak becomes the Keep Offset child of its corresponding FK; the Tip belongs to the final FK. ORG parenting and constraints remain in place. FK-to-FK Connected flags are restored from the original chain. Selecting any ORG, Tweak or Tip belonging to a generated chain builds that whole chain. Existing complete chains are rejected, so repeated clicks do not create duplicates.

The Tweak and FK sections each have a separate **Specify Collection** switch. Enabled: choose an existing collection, including nested collections. Disabled: use the armature's currently active bone collection at the time of that button click. The active collection is shown below the switch. If there is no active collection, select one first. New bones belong only to the chosen collection; source membership is unchanged. Collection creation is not automatic.

New Tweak, Tip and FK bones have Deform disabled. They are created from rest geometry without copying source constraints, animation, drivers, custom properties or pose offsets. Source animation/constraints/drivers are retained. Existing animation or drivers that already address a proposed new bone name are rejected to keep new controls clean. This is a rest-rig construction operation, not an animation bake; existing source poses may evaluate differently after reparenting.

Naming automatically strips an existing `ORG_` or `ORG-` marker, outer whitespace and trailing duplicate numbers such as `.001`, including before/after `.L` and `.R`. The marker is optional; other names use their full base name. Meaningful numbering such as `_01` remains. `ORG_Stick_01.L.001` produces `Stick_01_Tweak.L` and `Stick_01.L`; its terminal Tip is `Stick_01_Tip_Tweak.L`. If a source without an ORG marker already has the exact planned FK name, the existing name-conflict check stops FK creation. Rename that source (e.g. add `ORG_`) before clicking Create FK; stable identity links preserve the association and planned FK name.

Original-chain data and stable bone identities are saved on the armature and survive saving/reopening and addon reloads. Source, Tweak and Tip renames are supported between steps; planned FK names remain based on original source names. Keep the original external parent name and source rest geometry stable between buttons. Deleting generated bones, changing their hierarchy, or changing source rest geometry is reported instead of guessed. Settings are stored per armature. Both operations preserve selection/mode, support Undo, and roll back partial changes on failure. No blend file is saved automatically.

## RIG Tools: MCH Socket

In Edit or Pose Mode, select the active source controller (a selected head alone works in Edit Mode). This tool uses that one active bone, even if other bones are selected. It creates both mechanisms at the source's rest head, preserving the source's rest orientation, length, Deform flag, pose channels, animation and constraints.

- **World Axis:** +Z Up (default), +Y Back, +X Right, or their negative directions. The bones' head-to-tail axes follow the chosen world axis at creation time, accounting for the armature object's current world rotation and scale. This is a rest orientation, not an ongoing world-axis constraint.
- **Socket Length / INT Length:** independent custom lengths in armature space, default 1.0 and 0.5, displayed in scene length units.
- **Root:** leave empty to automatically find the unique bone named ROOT/root/Root, case-insensitively; choose an existing bone explicitly for another name or ambiguous matches.
- **Rotation Follow:** initial Copy Rotation influence, **default 1**. Set to 0 to isolate Socket rotation while retaining ROOT rotation; adjust the created constraint's influence afterward as needed. Position and scale influences are always 1.
- **Specify Collection:** enabled assigns both new bones only to an existing selected collection (including nested collections); disabled uses the current active collection.

For `Controller.L.001`, the names are `MCH_Socket_Controller.L` and `MCH_INT_Socket_Controller.L`. Duplicate number suffixes are removed before/after `.L` and `.R`; the remaining controller name, including any ORG marker, is retained.

`MCH_Socket` inherits the source's previous parent using Keep Offset; when the source had no parent, Socket remains unparented. `MCH_INT_Socket` is a Keep Offset child of Root; the source becomes a Keep Offset child of INT. Both generated bones have Deform disabled and no copied animation/drivers. INT has exactly three constraints targeting Socket, in this order: **Copy Location → Copy Scale → Copy Rotation**. All use World Space for owner and target and Blender's native default axis/mix settings. The default influences are **1 → 1 → 1**.

This builds rest rigging and does not bake/compensate existing animation. Missing/ambiguous roots, a Root that is the source or its descendant, conflicting names/animation, invalid world transforms and read-only/shared data are rejected. Repeat clicks do not overwrite existing mechanisms. Edit/Pose Mode and selection are preserved, Undo is supported, and a failed operation removes partial mechanisms and restores the source hierarchy/rest data. No blend file is saved automatically.

## RIG Tools: Rotation Follow

[Chinese workflow and limits](ROTATION_FOLLOW_zh.md). This tool operates only on a local, editable, single-user active armature in Edit or Pose Mode. It creates Copy Rotation constraints, not a transform blend or animation bake.

1. Choose an explicit **Rotation Source**, select the affected bones, then **Load Selected**. This freezes the displayed **Affected Bones** list; later selection changes do not silently change its scope. To choose another range, Load Selected again. This action also previews a fresh distribution and stores stable bone identities.
2. Choose **Direct Constraint** or **MCH Parent**. In Direct mode, Connect Rotation places a managed Copy Rotation on each affected bone, before its first Stretch To or at the end when none exists. Other constraints retain their relative order. In MCH mode, **Create MCH** first inserts `old parent → MCH_ROT_<controller> → controller` with Keep Offset. New MCHs keep the controller's head/orientation/roll, have configurable length (default 0.3), use the active or specified existing collection, disable Deform, and copy no animation, constraints or user properties. Controllers retain their rest geometry. The original parent and Connected flag are recorded; Connected is disabled where the new head/tail do not match, rather than moving the controller.
3. In MCH mode, adjust the mechanisms' rest orientation and length in Edit Mode as needed. Save/reopen or addon reload is supported at this stage. **Connect Rotation** reads their actual adjusted rest frames; it does not restore the initial MCH geometry. Original-controller rest edits or changed hierarchy are reported.
4. **Auto Falloff** is off by default: all preview/applied base values are 1. With it on, **Apply Falloff** distributes the editable Start/End values (default 0.2/0.8) linearly by parent-chain index. Independent continuous chains restart the distribution; a single bone uses Start. Branches, internal gaps and overlapping selections are rejected. Physical lengths, names and selection order do not determine weights. Load Selected and Apply Falloff are the only distribution triggers; per-row edits are not overwritten when changing endpoints. Switching Auto Falloff off resets the preview to 1; the next explicit Connect/Property operation applies 1.
5. **Constraint Options** exposes all native Copy Rotation mix modes and non-Custom spaces, with XYZ switches and per-axis inversion. Defaults are Local / Local / Replace and XYZ enabled. Custom is omitted because this version has no Custom Space reference fields. UI setting changes are previews until an explicit operation writes them.
6. Optionally enable **Connect Follow Property**, explicitly choose a Property Bone and Existing/New Property, then **Connect Property** after rotation is connected. A new property is a float, value/default 1 and range 0..1. Existing finite numeric scalar values within 0..1 are accepted without changing their value, UI range or animation. Each managed influence gets a driver `total * previewed base`. Connect Rotation can subsequently update coefficients without hand-editing drivers. Property operations apply the preview coefficients too; other constraint options still require Connect Rotation. **Disconnect Property** removes only the verified owned drivers and restores previewed base values; it never deletes the shared property. Hiding the property section does not unlink existing drivers.

Records on the armature track affected/source/MCH/property bones by stable identities. Bone renames survive updates, save/reopen and reload; deletion followed by a same-name replacement is not treated as the original bone. Repeated Create MCH skips verified existing mechanisms; repeated Connect Rotation updates them without nesting or adding duplicate constraints. A mode switch on an existing binding is rejected as a structural rebuild, not performed by an ordinary update. There is no cross-mode conversion or general structure-removal operator.

**Changing an existing MCH length:** edit MCH Length, then click **Update Length**. It preserves the MCH head, orientation/roll, controllers, constraints, drivers and collections. It rejects Connected children that would otherwise be moved. No deletion is necessary.

**After manually deleting an MCH:** use **Recreate Missing** to restore only missing recorded mechanisms in the affected list. Existing MCHs are skipped. Recovery checks the original controller rest geometry/parent, source, property mapping and name/animation conflicts, then creates clean MCHs at the chosen length and collection. New MCHs start with the controller's rest orientation; deleted manual MCH alignment must be adjusted again. Rotation is left pending: inspect the recovered bones, then **Connect Rotation**. Existing total-property mappings are retained for reconnection; shared property values are unchanged. Save/reopen, rollback and native Undo/Redo are supported. Same-name replacements and unrelated user data are not adopted or deleted.

Only registry-owned constraints with their unique token, target/source identity, settings and driver signature intact are updated. Existing user Copy Rotation, Copy Transforms or IK on an intended constraint owner is reported as a conflict. User-edited/renamed/missing constraints and edited/foreign drivers are not adopted or overwritten. Blender constraints have no custom ID-properties: the persistent registry and multiple integrity checks provide ownership evidence; an indistinguishable manually recreated copy of the full recorded mechanism cannot be distinguished after reopening. Checks reject obvious same-armature parent/constraint/transform-driver cycles; they do not prove arbitrary cross-rig or scripted dependency graphs safe.

Rest-geometry checks compare head position, actual length and normalized orientation separately. Edit Mode/import roundoff can slightly change near-unit rest-matrix column lengths without changing the bone geometry. Only near-rigid frame drift up to 0.00005 is normalized; the 0.00001 position, length and normalized-axis tolerances remain. Significant scale/shear, reflection, degenerate/non-finite frames and real rest edits still fail. A roundoff warning is not a reason to clear an already bound bone's identity.

Operations restore selection, active object and Edit/Pose Mode, support native Undo/Redo, prevalidate the full affected range, and roll back their own partial structure/constraint/driver/property changes on failure. Reports show new/updated/skipped/conflict counts and named entries; Details and the console contain the full result. No blend file is saved, source animation cleared, rotation mode changed, or animation baked/compensated automatically.

Moderate rotations and rotated/nonuniformly scaled objects are tested against independently built native Copy Rotation references. Nonuniform scale, differing rest axes and native space conversion can introduce shear or axis coupling; influences are native rotation blending weights, not guaranteed component-wise Euler angle multipliers. This tool preserves native behavior and performs no shear compensation or pose matching. Singular/non-finite object transforms are rejected. Optional Align to Source is not exposed: the confirmed default keeps controlled orientation and permits manual MCH adjustment.

Implementation: `rotation_follow.py`; `rig_common.py` supplies reusable stable identity, isolated context/rollback and clean MCH insertion primitives. Existing Tweak/FK and Socket backends and records are unchanged. Acceptance test: `tests/test_rotation_follow_blender.py`; machine-readable results: `outputs/rotation_follow_test_report.json` in the development workspace.

## RIG Tools: Arm

Version 0.10.0 adds an independent **Arm** section alongside Tweak / FK, MCH Socket and Rotation Follow. Start with an already adjusted three-bone main Tweak arm; generic Create FK is not required. [Full Chinese workflow, recovery rules and calibration limits](ARM_zh.md).

Fill seven explicit ORG/Tweak/Tip role mappings, or Load Tweak Mapping from an existing three-bone OZO record. Use the five separate buttons: **Create Switch Chain → Create FK / IK Chains → Create IK Controls → Connect IK → Connect IK/FK Switch**. Each stage permits inspection, manual rest adjustment, save/reopen continuation and Undo/Redo. Completed creation/connection buttons validate and skip existing results. **Update Pole Placement / Length**, **Update IK Parameters** and **Match Rest Bend** explicitly apply numerical changes.

Switch roots inherit the Arm Tweak's previous parent; FK/IK roots read the Switch root's current parent at stage 2. Hand IK and Pole initially use an explicit or unique case-insensitive ROOT. Pole defaults to the upper-arm tail offset along that bone's local X, equivalent to duplicating/translating an upper-arm locator. Its axis is world +Y with Roll recalculated against world +Z. Distance/flip/length, legacy rest-plane/explicit positioning and an optional display rod are available. **Align Pole: Upper Arm X** explicitly fixes existing stage 3/4/5 controls in place; Create/Load preserve their current placement. Choose Bend Axis explicitly. IK solves two bones; Hand uses World/World Replace Copy Transforms. Match Rest Bend searches and verifies actual evaluated bend in a disposable rig, then validates the live branch after writing only the owned Pole Angle. Run it after aligning/repositioning Pole: local-X placement alone does not guarantee Pole Angle=0 with arbitrary 3D rest axes. It rejects degenerate/unreachable targets, nonuniform/reflected/sheared object transforms, non-neutral solver channels, constrained/posed root ancestors and additional IK limits/stiffness.

The integer property defaults to Arm_FK_IK.L/.R, value/default 0, range 0..1: **0=FK, 1=IK**. Existing compatible integers can be explicitly reused without resetting values, metadata or animation. Each Switch has FK Copy Transforms at influence 1, followed by driven IK Copy Transforms (ik_fk == 1), World/World Replace. Separate records and stable bone identities preserve renames and multiple instances. Corruption, foreign mechanisms, edited owned constraints/drivers, name/animation conflicts and obvious same-rig cycles are reported instead of silently rebuilt. No automatic blend save, bake, pose matching, parent switching, Leg, Twist or Foot Roll is included.

Tests: tests/test_arm_blender.py, tests/test_arm_edgecases.py, ZIP install and full module hot reload. Reports: outputs/arm_test_report.json and outputs/arm_edgecases_report.json. Only synthetic rigs are used.

## RIG Tools: Bone Identity

Blender copies internal IDs when duplicating bones. Click **Repair Duplicate IDs** in Edit or Pose Mode to scan the active armature, covering both `ozo_rig_identity` (Rotation Follow/Arm) and legacy `ozo_control_bone_id` (Tweak/FK). Selection is unnecessary for automatic repair. Recorded parent links, constraint owners/targets, property drivers and rest geometry identify originals; linked identities from the other OZO system can confirm them. Original IDs and saved records stay intact, while copies receive new IDs. Names and bone order are never used to break ties. Unbound duplicate groups receive new IDs on every member. [Chinese workflow](BONE_IDENTITY_zh.md).

The report distinguishes repaired bones and unresolved groups; **Details** names each group and explains why it remains unresolved. Identical full copies or contradictory evidence are left unchanged. For ambiguous originals, expand **Manual / Advanced**, select all copies of one group, leave the original unselected and choose it in **Original Bone**, then retry Repair Duplicate IDs. An explicit choice cannot override contradictory evidence. The old **Clear Selected Identity** remains an advanced shared-ID-only operation with its original binding protection; it does not clear legacy IDs.

Only duplicated IDs on the active local editable single-user armature are repaired. Unique bound IDs, rest geometry, parenting, Deform, collections, pose channels, constraints, drivers and other custom properties are preserved. Re-keyed shared-ID input caches/affected-list rows are reset; Load Selected again for copied controllers afterward. Unknown referenced records are protected. Safe groups are repaired even when other groups remain unresolved; runtime failure rolls back the entire write batch and caches. Undo/Redo and save/reopen are supported. No blend is saved, no rig is rebuilt, and repair does not fix unrelated structural/constraint changes. Tests: `tests/test_identity_repair.py`, `tests/test_identity_repair_arm.py`, plus the original identity and rig suites.

## Animation Scale

This tool makes a constant positive uniform armature object scale equal to 1 while preserving the current Action's world-space motion and size. It does not match a character's height or retarget an animation. [Chinese explanation and manual workflow](ANIMATION_SCALE_zh.md).

1. Select the imported armature in Object or Pose Mode with the intended Action active.
2. Open Animation Scale and click **Check**. The information button shows eligibility or specific unsupported features. Expand **Scope** for a short support summary.
3. Click **Normalize Scale**. Copies of the armature data, direct-child mesh data, and active Action are created. The original Action is retained with a fake user. The copied Action becomes active.
4. The tool verifies every integer Action frame (including keys outside a manually set Action range), fractional key times, and the current frame. It compares every bone's world-space head/tail and all evaluated vertices of every affected mesh. The Object Scale must stay at 1. The information button shows measured errors and the Action names.

Both keyed bone location values and their left/right handles are multiplied by the original scale. Unkeyed bone locations receive the same conversion. Rest data and mesh vertices receive that uniform factor. Object Scale keys and handles become 1. Object location/rotation, bone rotation/scale, keyframe times, and the original Action curves remain unchanged.

Supported: one local, unparented armature; positive uniform constant scale; one active Action slot/layer/keyframe strip using Replace at influence 1; optional direct mesh children with near-identity local and parent-inverse matrices; one vertex-group Armature modifier per mesh. Matrix elements may deviate from identity by at most 0.00001 to accommodate import roundoff. Residual linear transforms are retained, not cleared; residual translation is converted by the same uniform factor, keeping mesh-relative units consistent. Larger transforms are still rejected, and the independent world-error threshold remains 0.00002 Blender units. Multiple such meshes and an armature without meshes are supported. Shared Actions are safe because the Action is copied, while shared armature/mesh geometry is rejected.

Unsupported inputs are rejected before any copies are created: dynamic/nonuniform/negative/zero scale, constraints, drivers, NLA tracks, delta transforms, shape keys, shared geometry, linked/overridden data, custom bone shapes, segmented B-Bones, FCurve modifiers or sampled curves, extra modifiers, complex parenting/mesh transforms, instancing, external rig users, and scene time remapping. Before a non-unit conversion, frame callbacks are checked individually. Audited AMP Animate Pro playback callbacks are compatible when playback is stopped; audited Auto-Rig Pro animated-layer callbacks are compatible when animated layers are disabled. Matching includes a source-code fingerprint, so changed code is not trusted just by name. Other callbacks are identified by module/function in the report and block a conversion. Callbacks are never removed, disabled, or reordered. Empty transform channels with no modifiers/samples are retained; normal keyed channels and unkeyed pose values remain supported.

Verification is mandatory. The baseline memory limit is 512 MiB. The error threshold is 0.00002 Blender world units; very large coordinates or numerically unstable cases may fail and roll back. No blend file is saved. A failed transaction restores old data, Action, fake-user state, object scale, mesh transform channels and parent-inverse matrices, pose channels, and frame, then removes its temporary copies. Successful execution also restores frame/subframe and keeps active object, selection, and mode. Blender Undo/Redo is supported.

Already normalized inputs report Already Scale 1 in Check and are skipped without new copies or frame stepping. Unrelated frame callbacks do not block this no-op. An internal binding identifies matching normalized rig/Action data and prevents baking a converted rig again using an unconverted backup Action. Only the active Action is converted: do not apply old, unconverted Actions to the normalized rest data. Process other original clips from an original rig copy. To revert the complete conversion, use Undo or reopen your source blend; selecting the old Action alone does not revert rest/mesh data.

## Development

Features live in separate modules registered through `__init__.py`. Copy Transform is implemented in `bone_constraints.py`.

Version 0.10.6 adds one-click duplicate identity repair for both legacy Tweak/FK and shared Rotation Follow/Arm IDs. Original ownership is inferred from recorded physical links, with ambiguity details and an explicit fallback; binding records and rig structure are preserved.

Version 0.10.5 releases all upper-arm IK rotation axes; Elbow Bend Axis applies only to the forearm. MCH_IK_Hand is unparented and follows Hand_IK via Copy Transforms; the forearm IK constraint targets MCH_IK_Hand. Enable Stretch remains on by default. Sync / Repair IK Setup adopts the existing native elbow hinge, stretch toggle/weights and Pole Angle, releases shoulder locks, detaches/rewires the existing owned Hand mechanism, and updates persistent settings without recreating the chain or resetting control poses. Native elastic IK can still change length; inward motion is tested to produce actual elbow bending, with stretch both on and off. This implements the user's confirmed correction to the original stage-2 hand parenting and stage-4 target.

Version 0.10.4 fixes Arm Pole creation: upper-arm local-X locator placement, world +Y extrusion with +Z Roll, and explicit in-place alignment for existing controls. Tests compare an independent EditBone construction and reconstruct the reported 3D sample from read-only coordinates, including evaluated IK calibration, Undo/Redo and rollback.

Version 0.10.3 fixes false controlled-rest-change conflicts caused by imported rest-frame normalization roundoff, without widening the position/length thresholds or changing rig records. Exact reported matrices and native MCH continuation are covered by tests/test_rest_geometry_roundoff.py.

Version 0.10.2 adds Bone Identity cleanup for copied/new controllers, explicit original retention for bound copies, and stale preview/cache cleanup. Existing Arm and Rotation Follow backends are retained.

Version 0.10.1 adds explicit Rotation Follow Update Length and Recreate Missing operations; the 0.10.0 Arm implementation and shared rig primitives are retained unchanged. Acceptance: tests/test_rotation_follow_mch_maintenance.py.

Version 0.10.0 adds the independent five-stage Arm module, stable per-instance records, explicit control/IK updates, evaluated Match Rest Bend calibration and integer FK/IK switching. See ARM_zh.md.

Version 0.9.0 adds staged Direct/MCH Rotation Follow, explicit affected lists, editable chain falloff, optional total-property drivers and shared MCH primitives; no other candidate rigging tools are added.

Version 0.8.1 separates RIG Tools from the OZO_Tools parent panel while keeping the same sidebar tab; Tweak / FK and MCH Socket now have independent collapsible subpanels.

Version 0.8.0 renames ORG Controls to RIG Tools and adds MCH Socket creation in `bone_socket.py`, with world-axis orientation, ROOT lookup, ordered world-space copy constraints and default rotation influence 1.

Version 0.7.1 removes the ORG Prefix field/filter from ORG Controls and explicitly displays the current selection on the active armature.

Version 0.7.0 adds ORG Controls in `bone_controls.py`: separate Tweak/FK construction, custom lengths, optional existing collections, clean non-deforming controls and persistent original-chain records.

Version 0.2.0 adds the English parent/subpanel layout, compact reporting, and configurable spaces, mixing, and influence.

Version 0.2.1 aligns subpanel contents with the header indentation and removes doubled punctuation from A/B labels.

Version 0.3.0 adds the Deform subpanel and one-click disabling of deformation on non-DEF/non-ROOT bones.

Version 0.3.1 makes Deform repair bidirectional and treats both DEF and ROOT as prefixes.

Version 0.4.0 adds manual DEF hierarchy templates, a selectable root bone, and original-parent restoration.

Version 0.5.0 adds Animation Scale with eligibility checks, copied Actions/data, mandatory world-space verification, rollback, and Undo/Redo.

Version 0.5.1 fixes the blanket frame-callback rejection, adds guarded AMP/ARP compatibility, and reports already-unit inputs without executing callbacks.

Version 0.5.2 accepts near-identity import matrices, converts residual offset units, improves matrix error reporting, and preserves the existing world-space verification tolerance.
