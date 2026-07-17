---
name: video-frames
description: "Analyze video by sampling frames with ffmpeg and running vision_analyze per frame — for clips too large for video_analyze, frame-accurate inspection, CCTV footage review, and timelapse summaries."
version: 1.0.0
author: community
license: MIT
platforms: [linux, macos, windows]
metadata:
  fabric:
    tags: [Video, Computer-Vision, ffmpeg, Frames, CCTV, Analysis, Media]
    related_skills: [frigate]
prerequisites:
  commands: [ffmpeg]
---

# Video Frame Analysis

`video_analyze` sends a whole clip (≤50MB) to a video-capable model. When
that doesn't fit — big files, frame-accurate questions, or no video-capable
auxiliary model configured — sample frames with ffmpeg and analyze them
individually with `vision_analyze`.

## When to Use

- Clip larger than 50MB, or `video_analyze` reports no capable model
- "What exactly happens at 0:42?" (frame-accurate)
- CCTV/Frigate footage review (pair with the `frigate` skill)
- Summarizing long recordings cheaply: sparse frames ≪ full video tokens

## Workflow

Write frames into the vision-readable cache so `vision_analyze` can load
them even under a sandboxed terminal:

```bash
FRAMES_DIR="${FABRIC_HOME:-$HOME/.fabric}/cache/vision/frames_$(date +%s)"
mkdir -p "$FRAMES_DIR"

# 1 frame per second (adjust fps to the question)
ffmpeg -i clip.mp4 -vf fps=1 -q:v 3 "$FRAMES_DIR/f_%04d.jpg"

# Or: only frames around a timestamp
ffmpeg -ss 00:00:40 -t 5 -i clip.mp4 -vf fps=2 -q:v 3 "$FRAMES_DIR/t40_%02d.jpg"

# Or: scene-change keyframes only (best frames-per-token ratio)
ffmpeg -i clip.mp4 -vf "select='gt(scene,0.3)',showinfo" -vsync vfr "$FRAMES_DIR/s_%03d.jpg"
```

Then analyze selectively — NOT every frame:

1. `ls "$FRAMES_DIR"` and count.
2. Pick a spread (first/middle/last, or around the timestamp of interest).
3. `vision_analyze(path)` per chosen frame with a specific question.
4. If the answer is between two frames, resample just that interval at
   higher fps.

## Rules of Thumb

- 3–8 analyzed frames answer most questions; more frames = more context
  burned for little gain, and images are re-sent every turn once in history.
- Cap extraction: `-vf fps=1` on an hour-long file makes 3600 frames.
  Bound with `-t <seconds>` or `-frames:v <n>` — extract what you'll read.
- Keep frames ≤1080p (`-vf "fps=1,scale=1280:-2"`) — oversized images cost
  tokens and can hit provider pixel limits.
- Run one ffmpeg at a time; parallel per-frame encode fan-out has saturated
  hosts before (see vision_tools incident notes).
- Clean up the frames dir when done: `rm -rf "$FRAMES_DIR"`.

## Verification

After extraction, spot-check one frame with `vision_analyze` before
analyzing the batch — a wrong `-ss` offset or rotated stream is cheaper to
catch on frame one.
