---
name: openpi
description: "Deploy and drive Physical Intelligence openpi VLA policies (pi0, pi0-FAST, pi0.5) — run the websocket policy server, wrap it as a ROS 2 skill server, issue language subcommands, fine-tune on LeRobot data."
version: 1.0.0
author: community
license: MIT
platforms: [linux]
metadata:
  fabric:
    tags: [Robotics, VLA, openpi, LeRobot, Manipulation, Embodied, GPU]
    related_skills: [ros2-gazebo]
    homepage: https://github.com/Physical-Intelligence/openpi
---

# openpi (π0 / π0-FAST / π0.5)

[openpi](https://github.com/Physical-Intelligence/openpi) is Physical
Intelligence's open-source vision-language-action (VLA) stack: model
weights + training/inference code for π0 (flow matching), π0-FAST
(autoregressive), and π0.5 (open-world generalization), with fine-tunes
for DROID, ALOHA, and LIBERO platforms.

## The Layering (get this right first)

You are the TOP loop. Do not try to be the bottom one.

| Loop | Component | Rate |
|------|-----------|------|
| Task planning, monitoring, replanning | Fabric agent | seconds–minutes |
| Controllers, safety, navigation | ROS 2 (ros2-gazebo skill) | 10–100 Hz |
| Manipulation skills | openpi policy server | ~50 Hz action chunks |

The validated interface between you and the VLA (per PI's Hi Robot /
π0.5 work) is **short imperative language subcommands**: "pick up the red
block", "open the drawer". You issue one, watch for success/failure via
ROS topics or the client result, and replan on failure.

## Hardware Requirements

- Inference: NVIDIA GPU > 8 GB VRAM (a π0 checkpoint is ~14 GB on disk)
- LoRA fine-tune: > 22.5 GB VRAM; full fine-tune: > 70 GB (multi-GPU)
- Ubuntu 22.04+, JAX runtime (PyTorch port exists for inference)

## Run the Policy Server (GPU box)

```bash
git clone --recurse-submodules https://github.com/Physical-Intelligence/openpi.git
cd openpi && GIT_LFS_SKIP_SMUDGE=1 uv sync

# Serve a DROID-tuned checkpoint on the default port 8000 (websocket)
uv run scripts/serve_policy.py --env DROID
```

Run it as a Fabric background process so you get notified on crashes:

```
terminal("cd ~/openpi && uv run scripts/serve_policy.py --env DROID",
         background=true, watch_patterns=["error", "Serving"])
```

## Call the Policy (robot side)

The `openpi-client` package is dependency-light and runs on the robot:

```python
from openpi_client import websocket_client_policy, image_tools

policy = websocket_client_policy.WebsocketClientPolicy(host="<gpu-box>", port=8000)
action_chunk = policy.infer({
    "observation/exterior_image_1_left": image_tools.resize_with_pad(img, 224, 224),
    "observation/joint_position": joint_pos,
    "observation/gripper_position": gripper,
    "prompt": "pick up the red block",
})["actions"]   # execute chunk on the robot at control rate
```

Wrap this in a thin ROS 2 action server (`execute_skill(language_command)
→ success/failure`) so the agent layer stays transport-clean: you call the
action, the node streams observations to the policy and executes chunks.

## Expectations

- Zero-shot on YOUR robot generally does not work. DROID-platform robots
  get closest with `pi0-FAST-DROID`. Everything else needs fine-tuning on
  your own demonstrations (LeRobot dataset format, 50–100 episodes is a
  typical starting point).
- Lightweight alternative: LeRobot's SmolVLA (~2 GB) with its gRPC async
  PolicyServer — same layering, smaller GPU.

## Safety Rules

- The VLA moves the arm. Velocity/torque limits, workspace fencing, and
  e-stop live BELOW the policy in the controller stack — verify they are
  active before the first `infer` call on hardware.
- Test every new checkpoint in simulation (LIBERO/ALOHA sim or your Gazebo
  scene) before hardware.
- One subcommand at a time; wait for terminal success/failure before the
  next. Never queue actuation.

## Pitfalls

- Don't ship checkpoints inside skills or repos — pull them at deploy time
  (openpi downloads from GCS on first use; cache with `OPENPI_DATA_HOME`).
- The websocket server holds ONE policy; switching tasks across different
  fine-tunes means restarting with a different checkpoint.
- If actions look erratic, check image preprocessing first —
  `resize_with_pad(…, 224, 224)` and camera-name mapping must match the
  fine-tune's config exactly.
