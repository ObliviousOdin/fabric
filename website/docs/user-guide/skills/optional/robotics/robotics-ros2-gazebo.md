---
title: "Ros2 Gazebo"
sidebar_label: "Ros2 Gazebo"
description: "Control and introspect ROS 2 robots and Gazebo simulations — ros2 CLI, rosbridge/MCP tool access, headless gz sim runs, colcon builds, and long-running launc..."
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Ros2 Gazebo

Control and introspect ROS 2 robots and Gazebo simulations — ros2 CLI, rosbridge/MCP tool access, headless gz sim runs, colcon builds, and long-running launches with background terminal processes.

## Skill metadata

| | |
|---|---|
| Source | Optional — install with `fabric skills install official/robotics/ros2-gazebo` |
| Path | `optional-skills/robotics/ros2-gazebo` |
| Version | `1.0.0` |
| Author | community |
| License | MIT |
| Platforms | linux |
| Tags | `Robotics`, `ROS2`, `Gazebo`, `Simulation`, `Embodied`, `Control` |
| Related skills | [`openpi`](/user-guide/skills/optional/robotics/robotics-openpi) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Fabric loads when this skill is triggered. This is what the agent sees as instructions when the skill is active.
:::

# ROS 2 + Gazebo

Drive a ROS 2 robot or a Gazebo simulation from Fabric. Three access paths,
in order of preference:

1. **ros-mcp-server** (`fabric mcp install ros2`): MCP tools for topic
   pub/sub, service and action calls, and parameter access over a rosbridge
   websocket — no changes to robot code. Best for interactive control.
2. **`ros2` CLI via the terminal tool**: `ros2 topic list/echo/pub`,
   `ros2 service call`, `ros2 node info`. Best for one-shot introspection
   and debugging.
3. **Background processes** for anything long-running (launch files, sims,
   bag recordings): `terminal(..., background=true)` with `watch_patterns`.

## When to Use

- "Launch the simulation and drive the robot to the goal"
- "Why is the navigation stack failing?" (topic echo, node info, TF checks)
- "Run the sim headless and report when it reaches the target"
- Building workspaces (`colcon build`), running `ros2 launch`, recording bags

## Environment Setup

ROS 2 must be sourced in the shell. The terminal tool persists exports
across calls, so run once per session:

```bash
source /opt/ros/jazzy/setup.bash        # or humble
source ~/ws/install/setup.bash          # your workspace overlay
```

No local ROS install? Use the Docker terminal backend — set in
`~/.fabric/config.yaml` (or env):

```
TERMINAL_ENV=docker
TERMINAL_DOCKER_IMAGE=osrf/ros:jazzy-desktop-full
TERMINAL_DOCKER_EXTRA_ARGS=["--network=host","--ipc=host"]
```

FastDDS needs shared memory — keep `--ipc=host` (or mount `/dev/shm`).
Add `--gpus all` for GPU perception/inference workloads.

## Long-Running Launches (the important pattern)

Foreground terminal commands are capped at 600s. Launch files and sims MUST
run in the background, with pattern-watching to wake the agent:

```
terminal("ros2 launch nav2_bringup tb3_simulation_launch.py headless:=True",
         background=true,
         watch_patterns=["[ERROR]", "Reached goal", "Navigation succeeded"])
```

Poll with `process(action="poll")`, read output with `process(action="wait")`,
stop with `process(action="kill")`. A watch-pattern match is delivered to you
as a new turn — do not busy-wait.

## Headless Gazebo

```bash
gz sim -s -r world.sdf            # server only, run immediately
gz topic -l                       # list gz topics
gz service -l                     # world control: pause/step/reset
```

Bridge Gazebo topics into ROS 2 so tools see one uniform surface for sim
and hardware (this is what makes agent-level control sim-to-real portable):

```bash
ros2 run ros_gz_bridge parameter_bridge /cmd_vel@geometry_msgs/msg/Twist@gz.msgs.Twist
```

## rosbridge for MCP Access

On the robot/sim host, before connecting the `ros2` MCP:

```bash
sudo apt install ros-jazzy-rosbridge-server
ros2 launch rosbridge_server rosbridge_websocket_launch.xml   # port 9090
```

## Safety Rules

- Safety-critical control (watchdogs, e-stop, joint/velocity limits) lives
  in ROS 2 controllers — NEVER in your loop. You sequence skills and set
  goals; controllers keep the robot safe at 100Hz.
- Before publishing to actuation topics (`/cmd_vel`, joint commands),
  confirm the robot is in a safe state and know how to stop:
  publish zero, or `ros2 lifecycle`/e-stop service if the stack has one.
- Never publish actuation commands in parallel; issue → observe → next.

## Pitfalls

- `ros2 topic echo` without `--once` streams forever — always use
  `--once` or `--timeout`, or run it as a background process.
- Mixed ROS_DOMAIN_ID between host and container = silent empty topic
  lists. Set `ROS_DOMAIN_ID` explicitly in TERMINAL_DOCKER_ENV.
- Gazebo GUI needs a display; agents should run `gz sim -s` (headless
  server) and verify state via topics, not pixels.
- After changing TERMINAL_DOCKER_IMAGE, remove the old labeled container
  or the sandbox silently reuses the previous image.
