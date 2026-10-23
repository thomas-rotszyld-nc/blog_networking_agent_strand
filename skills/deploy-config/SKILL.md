---
name: deploy-config
description: Deploy to the lab switches the configuration Infrahub rendered for them, or re-align a switch that drifted. Use when the user asks to deploy, apply, push, roll out, re-align or fix a switch configuration. The configuration always comes from Infrahub; nothing is typed by hand.
---

# Deploy Infrahub's rendering to the switches

Infrahub renders a complete startup-config per leaf (artifact `startup-config`). The only way to change a switch is
to replace its running configuration with that rendering. Three tools, in this order:

1. `render_configs()`: once per turn, first. Asks Infrahub to re-render the startup-configs on main and waits a few
   seconds. Infrahub does not re-render main by itself after a merge: without this call the preview compares the
   switch with an outdated rendering. The result says, per device, whether the rendering changed.
2. `preview_config(device)`: read-only. Shows the unified diff between the running configuration of the switch and
   Infrahub's rendering, or says there is "no difference".
3. `deploy_config(device)`: replaces the whole running configuration with the rendering and saves it. The user
   confirms on the terminal before anything is sent; a guard may refuse (no artifact, unsafe rendering, too many
   switches in one turn). A refusal comes back as the tool result: report it, do not retry.

## Procedure

1. Determine the devices concerned (`leaf1`, `leaf2`, or the one the user named).
2. Call `render_configs` once. If it returns an error, report it and stop: deploying an outdated rendering is worse
   than deploying nothing.
3. For each device, call `preview_config`. If it says "no difference", say so and do not deploy that device.
4. For each device with a difference, show the diff in two or three lines (what is added, what is removed), then call
   `deploy_config` once for that device.
5. Report per device: deployed, unchanged, refused (with the reason), or failed (with the error).
6. Offer to verify with the `vlan-check` skill.

## Never

- Send configuration lines by any other means, build or edit configuration text yourself, or ask the user to paste
  commands. If a change is needed in the configuration, it is a change of intent in Infrahub (`infrahub-change`),
  then a new deployment.
- Deploy a device whose preview you did not run in this turn.
- Retry a deployment the guard or the user refused.
