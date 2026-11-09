# SPDX-License-Identifier: GPL-3.0-or-later
"""Infer duplicate ownership from recorded physical links, never bone-name order."""
import uuid

from . import arm, bone_controls as controls, rig_common as rig, rotation_follow as follow

KEYS = (rig.BONE_ID, controls.ID_KEY)
RECORD_KEYS = (follow.RECORD_KEY, arm.RECORD_KEY, controls.RECORD_KEY)


def groups_for(data, key):
    groups = {}
    for bone in data.bones:
        uid = bone.get(key)
        if uid:
            if not isinstance(uid, str):
                raise ValueError(f"Invalid {key} on {bone.name}: expected a text identity")
            groups.setdefault(uid, set()).add(bone.name)
    return groups


class Evidence:
    def __init__(self, obj, groups):
        self.obj, self.groups = obj, groups
        self.tests = []

    def unary(self, uid, names, label):
        names = set(names) & self.groups.get(uid, set())
        if names:
            self.tests.append(((uid,), {(n,) for n in names}, label))

    def relation(self, left, right, pairs, label):
        if not left or not right or left == right:
            return
        pairs = {(a, b) for a, b in pairs if a in self.groups.get(left, ()) and b in self.groups.get(right, ())}
        if pairs:
            self.tests.append(((left, right), pairs, label))

    def parent(self, child, parent):
        pairs = [(name, self.obj.data.bones[name].parent.name)
                 for name in self.groups.get(child, ()) if self.obj.data.bones[name].parent]
        self.relation(child, parent, pairs, "recorded parent link")

    def geometry(self, uid, saved):
        self.unary(uid, [n for n in self.groups.get(uid, ())
                         if rig.same_geometry(self.obj.data.bones[n], saved)], "recorded rest geometry")

    def constraint(self, owner, name, kind, targets, link=None):
        matches = []
        for n in self.groups.get(owner, ()):
            c = self.obj.pose.bones[n].constraints.get(name)
            if c and c.type == kind:
                matches.append((n, c))
        self.unary(owner, [n for n, _ in matches], "recorded constraint owner")
        for field, uid in targets.items():
            target_field = "pole_target" if field == "pole_subtarget" else "target"
            self.relation(owner, uid, [(n, getattr(c, field, "")) for n, c in matches
                                      if getattr(c, target_field, None) == self.obj], "recorded constraint target")
        if link:
            pairs = []
            for n, c in matches:
                curve = rig.driver_for(self.obj, c.path_from_id("influence"))
                if not curve:
                    continue
                paths = {t.data_path for v in curve.driver.variables if v.type == "SINGLE_PROP"
                         for t in v.targets if t.id == self.obj}
                pairs.extend((n, target) for target in self.groups.get(link["bone"], ())
                             if follow.property_path(self.obj.pose.bones[target], link["name"]) in paths)
            self.relation(owner, link["bone"], pairs, "recorded property driver")

    def solve(self):
        domains = {uid: set(names) for uid, names in self.groups.items()}
        changed = True
        while changed:
            changed = False
            for ids, tuples, _ in self.tests:
                valid = [row for row in tuples if all(n in domains[uid] for uid, n in zip(ids, row))]
                for i, uid in enumerate(ids):
                    narrowed = domains[uid] & {row[i] for row in valid}
                    if domains[uid] != narrowed:
                        domains[uid] = narrowed
                        changed = True
        return domains


def evidence_for(obj, key, groups, rf, arms, chains):
    ev = Evidence(obj, groups)
    if key == rig.BONE_ID:
        for rec in rf["bindings"].values():
            owner = rec["mch"] if rec["mode"] == "MCH" else rec["controlled"]
            if rec["mode"] == "MCH":
                ev.geometry(rec["controlled"], rec["geometry"])
                ev.parent(rec["controlled"], rec["mch"])
                # A user may insert a copied collision/socket layer above the
                # real MCH. Its former parent alone cannot identify that MCH.
                if len(groups.get(rec["mch"], ())) == 1:
                    ev.parent(rec["mch"], rec["parent"])
            if rec["constraint"]:
                ev.constraint(owner, rec["constraint"], "COPY_ROTATION", {"subtarget": rec["source"]}, rec["link"])
        for rec in arms["arms"].values():
            mapping = {**rec["mapping"], **rec["bones"]}
            for role in arm.ROLES:
                ev.geometry(mapping["source_" + role], rec["sources"][role])
            for group, step in (("switch", 0), ("fk", 1), ("ik", 1)):
                if rec["steps"][step]:
                    for a, b in zip(arm.ROLES, arm.ROLES[1:]):
                        if group != "ik" or b != "hand":
                            ev.parent(mapping[group + "_" + b], mapping[group + "_" + a])
            for role in arm.ROLES:
                ev.parent(mapping["tweak_" + role], mapping["switch_" + role])
            ev.parent(mapping["tip"], mapping["switch_hand"])
            for saved in rec["constraints"]:
                ev.constraint(mapping[saved["owner"]], saved["name"], saved["type"],
                              {field: mapping[role] for field, role in saved["targets"].items()},
                              rec["link"] if saved.get("driven") else None)
    else:
        for chain in chains["chains"]:
            entries = chain["entries"]
            for i, entry in enumerate(entries):
                ev.geometry(entry["source"], entry)
                ev.parent(entry["source"], entry["tweak"])
                if chain["complete"]:
                    ev.parent(entry["tweak"], entry["fk"])
                    if i:
                        ev.parent(entry["fk"], entries[i - 1]["fk"])
                target = entries[i + 1]["tweak"] if i + 1 < len(entries) else chain["tip"]
                # Legacy Stretch To names were not recorded. Actual same-rig
                # targets are evidence; no constraint is adopted or changed.
                ev.relation(entry["source"], target,
                            [(n, c.subtarget) for n in groups.get(entry["source"], ())
                             for c in obj.pose.bones[n].constraints if c.type == "STRETCH_TO" and c.target == obj],
                            "Tweak Stretch To target")
            if chain["complete"]:
                ev.parent(chain["tip"], entries[-1]["fk"])
    return ev


def referenced(value, uid):
    if isinstance(value, dict):
        return uid in value or any(referenced(v, uid) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(referenced(v, uid) for v in value)
    return value == uid


def plan(obj, original="", selected=()):
    data = obj.data
    rf, arms, chains = follow.read_records(data), arm.read_records(data), controls.read_records(data)
    changes, details, conflicts = [], [], []
    selected = set(selected)
    groups_by_key = {key: groups_for(data, key) for key in KEYS}
    evidence = {key: evidence_for(obj, key, groups_by_key[key], rf, arms, chains) for key in KEYS}
    known_by_key = {rig.BONE_ID: (rf, arms), controls.ID_KEY: (chains,)}
    # One bone can have both legacy and shared IDs. A physically resolved,
    # recorded identity in either system anchors that same bone in the other.
    # This is essential for Arm inputs inherited from a Tweak chain.
    anchors = set()
    while True:
        solved = {key: ev.solve() for key, ev in evidence.items()}
        added = False
        for key, domains in solved.items():
            for uid, possible in domains.items():
                if (len(possible) != 1 or len(groups_by_key[key][uid]) < 2
                        or not any(referenced(r, uid) for r in known_by_key[key])):
                    continue
                name = next(iter(possible))
                for other in KEYS:
                    other_uid = data.bones[name].get(other)
                    token = (other, other_uid, name)
                    if (other != key and groups_by_key[other].get(other_uid) == groups_by_key[key][uid]
                            and token not in anchors):
                        evidence[other].unary(other_uid, [name], "original identified by another recorded OZO identity")
                        anchors.add(token)
                        added = True
        if not added:
            break
    for key in KEYS:
        groups, domains = groups_by_key[key], solved[key]
        known = known_by_key[key]
        for uid, names in groups.items():
            if len(names) < 2:
                continue
            label = f"{key}: {', '.join(sorted(names))}"
            unknown = [k for k in data.keys() if k.startswith("ozo_") and k not in RECORD_KEYS
                       and isinstance(data.get(k), str) and uid in data[k]]
            if unknown:
                conflicts.append(label + "; referenced by unknown record " + ", ".join(unknown))
                continue
            bound = any(referenced(record, uid) for record in known)
            possible = domains[uid]
            manual = original in names and original not in selected and names - {original} <= selected
            if bound:
                if len(possible) == 1:
                    keep = next(iter(possible))
                    if manual and keep != original:
                        conflicts.append(label + f"; Original Bone contradicts recorded links (retain {keep})")
                        continue
                elif manual and original in possible:
                    keep = original
                else:
                    reason = ("recorded links disagree; inspect changed mechanism links before repair" if not possible else
                              "original is ambiguous. Select copies and set Original Bone, then retry")
                    conflicts.append(label + "; " + reason)
                    continue
            else:
                # No persistent record depends on this number. Re-key every
                # member, so no arbitrary first bone is declared the original.
                keep = None
            for name in sorted(names - ({keep} if keep else set())):
                changes.append((key, name, uid, uuid.uuid4().hex))
                details.append(f"Re-keyed {name} ({key}); retained {keep or 'none: unbound group'}")
    return changes, details, conflicts


def apply_change(data, key, name, uid):
    data.bones[name][key] = uid


def apply(obj, changes):
    for key, name, _, uid in changes:
        apply_change(obj.data, key, name, uid)


def restore(obj, changes):
    for key, name, old, _ in changes:
        obj.data.bones[name][key] = old
