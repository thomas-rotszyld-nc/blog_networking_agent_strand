---
name: infrahub-change
description: Change the intent recorded in Infrahub (add or modify VLANs, assign an access VLAN to interfaces, change descriptions) on the agent's session branch and open a Proposed Change for a human to review and merge. Use when the user asks to add, create, rename, move or remove something in the source of truth. Never for deploying to switches.
---

# Change the intent in Infrahub

Infrahub is the source of truth and generates the switch configurations. You never edit the default branch: every
write lands on a session branch that the infrahub-mcp server creates for you on your first write, and reaches `main`
only through a Proposed Change that a human merges.

## Procedure

1. **Know the shape.** If unsure of a kind's attributes, relationships or human-friendly id (HFID), call `get_schema`
   with the kind (`IpamVLAN`, `IpamVLANGroup`, `InterfacePhysical`, `DcimDevice`). HFIDs in this lab: a VLAN is
   `["<name>"]`, a VLAN group is `["<name>"]`, an interface is `["<device name>", "<interface name>"]`.
2. **Read before writing.** `get_nodes` the objects you are about to touch (for example `IpamVLAN` with
   `include_attributes: true`), so the change is described from facts.
3. **Write with `mutate_graphql` when a relationship is involved** (`node_upsert` accepts scalar attributes only).
   Always ask the mutation to return `object { id }`. Examples:

   Create a VLAN in the site's group:
   ```graphql
   mutation { IpamVLANCreate(data: {
       name: {value: "GUESTS"}, vlan_id: {value: 40}, status: {value: "active"}, role: {value: "user"},
       vlan_group: {hfid: ["lab-vlans"]}
   }) { ok object { id } } }
   ```
   Put an interface on that VLAN as its access VLAN:
   ```graphql
   mutation { InterfacePhysicalUpdate(data: {
       hfid: ["leaf1", "Ethernet3"], l2_mode: {value: "access"}, untagged_vlan: {hfid: ["GUESTS"]},
       description: {value: "access port VLAN 40"}
   }) { ok object { id } } }
   ```
   Use `node_upsert` only for scalar-only edits (a description, a status).
4. **Tell the user the branch.** After the first write, call `get_session_info` and report `session_branch`: the
   branch did not exist before that write.
5. **Verify on the branch.** `get_nodes` with `branch: <session_branch>` for the kinds you changed; show the result.
6. **Open the Proposed Change.** `propose_changes` with a short title (what changed) and a description (why, which
   objects, which switches will be re-rendered). Give the user the link printed on the terminal.
7. **Stop there.** The human reviews the data diff and the rendered configuration diff in Infrahub and merges. Do
   not deploy anything until the user asks; deployment is the `deploy-config` skill.

## Never

- Write to the default branch, or ask to switch the session to it.
- Delete objects unless the user explicitly asked to delete that object.
- Send configuration to a switch from this skill.
