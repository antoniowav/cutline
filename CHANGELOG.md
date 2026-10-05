# Changelog

All notable changes to Cutline are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/antoniowav/cutline/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/antoniowav/cutline/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/antoniowav/cutline/releases/tag/v0.1.0
