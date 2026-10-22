---
name: vlan-check
description: Check the VLANs actually configured on the lab switches, and compare them with Infrahub when asked for compliance or drift. Use when the user asks to check, verify, audit, list or compare VLANs on a switch. Read-only.
---

# Check the VLANs on the switches

Switches are read through the netmiko tools; only `show vlan` and `show running-config` are allowed by the server.

## Procedure

1. If unsure of the device names, call `list_devices`.
2. For each device, call `send_show_command` with `command: "show vlan"` and `use_textfsm: true` (structured output:
   `vlan_id`, `vlan_name`, `status`, `interfaces`). Ignore VLAN 1.
3. Render one table per device: VLAN id, name, status, interfaces.
4. When the user asks whether a switch is compliant, or mentions drift: read Infrahub's VLANs for the site with
   `get_nodes` (kind `IpamVLAN`, `include_attributes: true`) and mark each switch VLAN `ok`, `renamed`, `missing` or
   `undocumented`; then run `preview_config(device)` from the `deploy-config` skill, whose diff is the authoritative
   view of the drift. Fixing it is a deployment (`deploy-config`), never a hand-typed command.
