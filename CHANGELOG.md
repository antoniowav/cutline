# Changelog

All notable changes to Cutline are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.14.0] - 2026-10-09

### Changed
- The inspector is a side panel next to the preview now, in sections (Picture, Motion &
  time, Colour, Text, Animation or Fades, Sound) instead of rows of controls under it.
  Crop, Look, Motion, Colour and Silences open in place and stay open while you work. On a
  narrow window the panel sits under the preview.
- Detach audio moved to the Sound section.

### Added
- Screenshots in the README.
- RELEASING.md: setting up the AUR package the first time.

## [0.13.0] - 2026-10-09

### Added
- Transitions on any track: full-screen clips joined by a transition above the bottom track
  now crossfade (or slide, wipe…) too, over whatever is below.
- Opacity can be keyframed (Motion ▾), like zoom and position.

### Changed
- Faster exports of HDR and other big clips: each clip is shrunk to the size it ends up at
  (with room for its zoom) before tone mapping, a LUT or a green screen. A 4K HDR iPhone
  clip in a 1080p export renders about 45 % faster.
- A zoom now happens inside the fitted or filled picture, in the preview and the export
  alike, so a moving zoom on a filled clip looks the same in both.
- In the preview, the clip coming in during a transition shows its LUT and green screen.

### Fixed
- Long edits with many captions export in small pieces again: a caption spanning a cut no
  longer ties the pieces on both sides together (one export opened 64 videos at once).
- An export that hits an unexpected error now stops with a message instead of hanging.

## [0.12.0] - 2026-10-09

### Added
- Voice enhance (Voice → Enhance / Enhance+ on any clip with sound): rumble cut, background
  noise taken down to the clip's own measured noise floor, a gentle gate that lowers the room
  between words, "s" softened, mud cut, presence lifted and compressed. On a laptop-mic
  recording the pauses come out 10-14 dB quieter. The preview plays the EQ and compressor;
  the noise removal is heard in the export.
- YouTube chapters: name your markers in Export → YouTube chapters and copy the list into
  the description (00:00 first, YouTube's rules checked). Exports carry the markers as
  chapters too, for players like mpv and VLC.

## [0.11.0] - 2026-10-09

### Removed
- Auto Shorts. Cutting a wide video down to a tall one didn't make Shorts worth posting,
  least of all from screen recordings; a Short recorded for it works better. With it go the
  bundled face model and the optional OpenCV and Claude Code. Follow the action (Motion ▾)
  and auto captions stay.

### Changed
- Crops are back to at most 45 % a side.

## [0.10.0] - 2026-10-09

### Added
- Follow the action (Motion ▾): Cutline watches where the picture changes (the cursor, typing,
  a window opening), zooms in there and back out when the whole screen changes or nothing
  happens for a while. Each move eases in and holds, so it never jitters, and it all lands
  as keyframes to adjust. A spot that keeps moving in the same place for minutes (a webcam
  bubble, a clock) is ignored. Made for screen recordings.
- Auto Shorts on screen recordings: when there's no speaker on camera, the whole screen is
  shown across the tall frame on blurred bars, following the action, with the captions
  below it.

### Changed
- Auto Shorts only follow a face that fills a good part of the frame, not a small webcam
  bubble on a screen recording.

## [0.9.0] - 2026-10-08

### Added
- Auto Shorts (＋ Title → Auto Shorts…): Cutline listens to the edit, picks the best moments
  (Claude Code reads the transcript text and picks them, or Cutline scores them itself),
  checks them against the transcript, cuts the pauses, makes each 9:16 with the crop on the
  speaker's face (OpenCV, with the YuNet model bundled), and adds word-by-word captions and a
  title. Each Short is a new project to check and export.

### Changed
- A crop can now take up to 90 % off a side (a wide video cropped to a tall strip).

## [0.8.0] - 2026-10-07

### Added
- ✂ Silences: find the pauses in the selected clips and cut them out, keeping a little
  around the words; what follows moves up. How quiet and how long a pause is can be set.
- Ducking: music set to "Duck under voice" drops about 12 dB while someone speaks and comes
  back in the pauses, in the export and in the preview.
- Auto captions (＋ Title → Auto captions…): whisper.cpp writes captions from the voices on
  the timeline, a few words or one word at a time, as text clips on a new CC track to fix
  and style like any title. Runs on this computer; the speech model (190 MB) is downloaded
  once on request. Needs whisper.cpp (on Arch: `sudo pacman -S whisper-cpp`; add
  `ggml-vulkan` to use the GPU).
- Thumbnail (in the export menu): the frame at the playhead, titles and all, as a PNG.

### Fixed
- Exports with no sound at all could fail (ffmpeg stopped on a silent branch).

## [0.7.0] - 2026-10-07

### Added
- Colour (Colour ▾): brightness, contrast, saturation and warmth, and one-click looks
  (Warm, Cool, Vivid, Punchy, Faded, Black & white, Noir). They apply to every selected
  clip at once, so a whole edit can be graded in one go. The preview and the export use the
  same colour matrix.
- LUTs: any .cube file in ~/Videos/LUTs or Downloads, applied in the export with lut3d and
  in the preview with WebGL.
- Green screen: take a colour out of a clip, picked with the eyedropper from the preview,
  with a strength and a soft edge. On a track above, what's below shows through.

## [0.6.0] - 2026-10-07

### Added
- Speed: 0.25x to 4x per clip, the sound keeping its pitch. What follows on the track moves
  along as the clip gets longer or shorter.
- Zoom and punch-in: zoom a clip in towards a focus point (Motion ▾), or press Z to punch
  in 120% on the clip at the playhead (Z again to go back).
- Keyframes: zoom, focus and a free clip's position can change over a clip. ◆ Key keeps the
  values at the playhead; a change anywhere else makes a key there. Moves ease in and out.
  Ken Burns adds a slow zoom across the clip in one click. Split keeps the motion on both sides.
- Opacity for videos and pictures, and fade in / fade out for them (picture and sound).
- Transitions: crossfade, dip to black, slide, wipe, circle or zoom into a clip from the
  full-screen clip right before it on its track. The sound crossfades too, and the timeline
  keeps its length to the frame.

### Changed
- The inspector's video controls wrap onto more rows instead of running off the window.

## [0.5.0] - 2026-10-07

### Added
- Pictures: photos and stickers (PNG, JPG, WebP) and animated GIFs and WebPs. Stickers keep
  their see-through parts in the preview and the export, and GIFs loop for as long as their
  clip. A picture added at the playhead goes in the middle, in its own shape; added to the
  end of V1 it fills the screen, like a slideshow. ~/Pictures is in the picker too.
- GIFs & SFX: buttons that open GIPHY (GIFs, stickers) or Pixabay (sound effects) in your
  browser. Cutline never talks to those sites: what you download shows up in the drawer,
  newest first, and a click adds it at the playhead.
- Drop files from the file manager onto the window, or drag a GIF or a sound straight from
  a web page: it's kept in Videos/Cutline media and added at the playhead. Fetching only
  reaches the internet, never this computer or the local network.

### Changed
- The header's ＋ Track button is gone (the timeline has its own), and the canvas size shows
  without the frame rate (hover for it), so the header fits on one line again.

## [0.4.0] - 2026-10-07

### Added
- Text looks: an outline, a drop shadow and a glow, each in any colour, and a box in any
  colour and opacity (Look ▾). Line text up on the left, centre or right of its spot.
- One-click styles: Plain, Subtitle, YouTube bold, Yellow punch, Neon, Highlighter and
  Red label, for every selected title at once.
- Text animations: in with a fade, pop, slide, typewriter or bounce; out with a fade, pop
  or slide. The preview and the export move the same way.
- Titles (＋ Title): a big title, a two-line lower third, a subscribe button and a chapter
  heading, ready to type over.

### Changed
- The header wraps on narrow windows instead of pushing Export off the screen.

## [0.3.0] - 2026-10-07

### Added
- Canvas shape: 16:9, 9:16 (Shorts, TikTok, Reels), 1:1 or 4:5, or like the video. The
  short side stays, so a 1080p project turns into 1080×1920.
- Fill (crop) for full-screen clips too, so a wide video covers a tall canvas.
- Blurred bars: the space around a full-screen picture is filled with a blurred copy of
  it instead of black. Applies to every selected clip at once.
- Export presets: a small file (720p, smaller) and a GIF (480p, 15 fps, its own palette).
- Loudness: export at -14 LUFS, how YouTube, TikTok and Spotify play it, measured in two
  passes so the level never pumps.

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

[Unreleased]: https://github.com/antoniowav/cutline/compare/v0.14.0...HEAD
[0.14.0]: https://github.com/antoniowav/cutline/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/antoniowav/cutline/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/antoniowav/cutline/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/antoniowav/cutline/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/antoniowav/cutline/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/antoniowav/cutline/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/antoniowav/cutline/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/antoniowav/cutline/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/antoniowav/cutline/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/antoniowav/cutline/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/antoniowav/cutline/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/antoniowav/cutline/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/antoniowav/cutline/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/antoniowav/cutline/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/antoniowav/cutline/releases/tag/v0.1.0
