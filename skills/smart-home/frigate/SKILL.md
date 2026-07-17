---
name: frigate
description: "Frigate NVR camera workflows — triage security alerts, analyze snapshots and clips with vision tools, search detection events, react to camera activity via MQTT or cron."
version: 1.0.0
author: community
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [Smart-Home, CCTV, Camera, Security, Frigate, NVR, Computer-Vision, Automation]
    related_skills: [openhue]
    homepage: https://frigate.video
prerequisites:
  env_vars: [FRIGATE_URL]
---

# Frigate NVR

[Frigate](https://frigate.video) is a local NVR with real-time object
detection. Fabric integrates with it on three levels:

1. **Tools** (`frigate` toolset): `frigate_events`, `frigate_reviews`,
   `frigate_snapshot`, `frigate_clip`, `frigate_status` — query the HTTP API
   and pull media. Enabled when `FRIGATE_URL` is set (`fabric tools` →
   Frigate NVR).
2. **Event ingestion** (`frigate` gateway platform plugin): subscribes to
   Frigate's MQTT review queue and wakes the agent on alerts.
3. **Vision analysis**: snapshots/clips downloaded by the tools are local
   files — pass them to `vision_analyze` / `video_analyze`.

## When to Use

- "What happened at the front door today?" / "Who was in the driveway?"
- "Check the cameras" / "Is anything unusual on camera right now?"
- Triage a Frigate alert that arrived via the gateway or a webhook
- "Watch for people in the backyard and tell me on Telegram"
- Diagnose a camera that stopped detecting (use `frigate_status`)

## Setup

- `FRIGATE_URL`: `http://<host>:5000` (Frigate's internal, unauthenticated
  port — use only on a trusted network) or `http://<host>:8971` with
  `FRIGATE_TOKEN` (JWT from `POST /api/login`; Frigate has no API-key header).
- Optional event push: enable the `frigate` platform plugin
  (`fabric plugins enable frigate-platform`) and set `FRIGATE_MQTT_HOST` to
  the broker Frigate publishes to. Alerts then arrive as agent messages.

## Triage Workflow

1. `frigate_reviews(severity="alert", limit=10)` — the curated queue.
   Alerts are the events Frigate considers important; `detection` items are
   routine. Each review item carries event IDs in `detections`.
2. `frigate_snapshot(event_id=...)` then `vision_analyze(path)` — describe
   who/what is in frame. Prefer the snapshot first; it is one image and cheap.
3. Only when the snapshot is ambiguous: `frigate_clip(event_id=...)` then
   `video_analyze(path)` (clips cap at 50MB), or sample frames with ffmpeg
   (see the `video-frames` skill).
4. Cross-reference: `frigate_events(camera=..., label="person",
   after=<unix_ts>)` for the raw detection history of a camera or zone.
5. Act: notify via `send_message`, or actuate lights/locks through the
   Home Assistant tools (`ha_call_service`) — e.g. turn on porch lights
   after a nighttime person alert.

## Scheduled Monitoring

Use `cronjob` for polling patterns ("summarize overnight camera activity
every morning at 8"):

- Prompt: "Call frigate_reviews for the last 12h (after=now-43200), analyze
  snapshots of alert items, summarize notable activity."
- `deliver=telegram` (or any configured platform) sends the digest out.
- A pre-run gate script can call `/api/review/summary` and skip the LLM
  entirely on quiet nights (`{"wakeAgent": false}`).

## Pitfalls

- **Do not fetch Frigate URLs with `vision_analyze` directly** — its SSRF
  guard blocks private/LAN addresses. Always download via `frigate_snapshot`
  / `frigate_clip` (they save into the vision-readable cache) and pass the
  local path.
- Event lists strip thumbnails deliberately; never request hundreds of
  events into context. Filter by camera/label/time and keep `limit` small.
- `frigate/events` MQTT topic fires on every tracked-object update; the
  platform plugin subscribes to `frigate/reviews` for a reason. Keep it that
  way unless you truly need per-object lifecycle noise.
- Port 5000 has no auth — never expose it beyond the local network.

## Verification

`frigate_status()` should return the Frigate version and per-camera FPS.
If a camera shows `camera_fps: 0`, the feed is down — check the camera
before blaming detection settings.
