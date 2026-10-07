# Changelog

All notable changes to Cutline are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-10-07

### Added
- Free layout: drag a clip anywhere in the preview and resize it from its corners, with
  snapping; Fit or Fill (crop) per clip.
- Side by side: the clips under the playhead in equal columns, e.g. three phone videos
  in one landscape frame.
- Music and voiceovers: add MP3, M4A, AAC, WAV, FLAC, OGG or Opus files from the videos
  folder or ~/Music with ＋ Media. They go on a track at the playhead and add sound only.
- Text: ＋ Text (or T) adds a title or caption at the playhead. Type it, set its size and
  colour, give it a box, drag it in the preview; it's trimmed and moved on the timeline like a clip.
- Fades: fade text and music in and out (seconds each way); the timeline shows the ramps.
- Fonts: pick any installed font for text, bold or not.
- Copy, cut and paste (Ctrl+C / Ctrl+X / Ctrl+V): anything selected, pasted at the playhead
  on the first free track. The clipboard works across projects and brings the videos along.
- Alt-drag a clip (video, sound or text) to drop a copy instead of moving it.
- Markers: M puts one at the playhead (or takes it away); [ and ] jump between them, and
  clips snap to them.
- Detach audio: a video clip's sound becomes a clip of its own, to move and trim apart.
- Crop and turn: cut off any edge of a clip's picture and turn it a quarter at a time.

### Fixed
- Long edits with many clips export again. The export used to open every clip's video at
  once, so a 15-minute 4K edit with a hundred cuts needed over 10 GB of memory and stalled.
  It now renders the timeline in pieces of a few clips each, mixes the sound on its own, and
  joins the pieces without encoding them again, still frame-exact.
- Faster exports: the picture is encoded on the GPU (VA-API) when it can be, with x264 as
  the fallback, and a smaller export is built at its own size instead of being rendered
  full size and shrunk at the end. Export at original size, 1440p, 1080p or 720p.
- The text colour now uses Cutline's own colour panel (swatches and a hex field) instead of
  the browser's dialog, which didn't show properly in the app window.
- Phone videos filmed in landscape no longer open in a portrait canvas: the
  rotation the phone tags them with is now taken into account.

## [0.1.1] - 2026-10-05

### Added
- Cuore's theme colours and font, as well as Omarchy's.

## [0.1.0] - 2026-10-04

First public release.

### Added
- Projects with a start screen: recent projects (rename, delete) and the videos in your Videos folder.
- Multi-track timeline: split, trim to playhead, edge trim/extend, ripple delete, gap selection and closing, box selection, snapping, undo/redo.
- Per-clip volume (0–200 %) and picture-in-picture layouts (full screen or any corner, 10–70 %).
- Background preview proxies (VA-API on the GPU, CPU fallback), thumbnail strips and waveforms.
- HDR → SDR tone mapping with libplacebo, falling back to zscale when libplacebo or Vulkan is missing.
- Frame-exact MP4 export at original size or 1080p.
- Live Omarchy theme colours and font, with a Tokyo Night fallback elsewhere.
- `--version`; `CUTLINE_BROWSER`, `CUTLINE_VIDEOS` and `CUTLINE_NO_BROWSER` settings.
- `install` / `uninstall` scripts for `~/.local`, a desktop entry, an icon and an Arch PKGBUILD.

### Fixed (since the private builds)
- Works with any Chromium-based browser (default browser first), and falls back to a normal browser tab.
- Respects `XDG_DATA_HOME`, `XDG_CACHE_HOME` and the XDG Videos folder.
- Timeline thumbnails were missing for clips with a single keyframe.
- Cancelling an export and starting another right away could fail the new one and delete its file.
- The local server now refuses requests from other web pages and other host names.

### Security
- The local server requires a session: the window swaps a one-time launch key for an HttpOnly, SameSite=Strict cookie.
  Other users on the same computer could previously drive the API (read videos, delete projects, write exports).
- Exports could be written outside the video's folder through a crafted project name (path traversal).
- Project values are validated before they reach ffmpeg's filter graph.
- Malformed requests (bad byte ranges, non-object JSON, oversized bodies) are rejected cleanly.
- Pages are served with a Content-Security-Policy, `nosniff` and `frame-ancestors 'none'`.
- CI: end-to-end tests, ruff/bandit, shellcheck, gitleaks, namcap, and CodeQL once public.

[Unreleased]: https://github.com/antoniowav/cutline/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/antoniowav/cutline/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/antoniowav/cutline/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/antoniowav/cutline/releases/tag/v0.1.0
