#!/usr/bin/env python3
"""End-to-end tests: start the real server, drive its HTTP API, export with ffmpeg.

    python3 tests/test_server.py

Needs ffmpeg. Everything happens in a temporary folder: your projects, cache and
videos are not touched.
"""

import http.cookiejar
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FPS = 30


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                          "stream=codec_type,codec_name,nb_read_frames,channels,color_transfer:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


class CutlineServer(unittest.TestCase):
    """The tests run in name order and share one server, like one editing session."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        cls.videos = tmp / "Videos"
        cls.videos.mkdir()
        cls.downloads = tmp / "Downloads"
        cls.downloads.mkdir()
        tone = ["-f", "lavfi", "-i"]
        ffmpeg(*tone, f"testsrc2=s=640x360:r={FPS}:d=4", *tone, "sine=f=440:d=4",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(cls.videos / "sdr.mp4"))
        ffmpeg(*tone, "testsrc2=s=640x360:r=25:d=3", *tone, "sine=f=330:d=3", "-ac", "1",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(cls.videos / "mono.mp4"))
        # 10-bit HLG, tagged like an iPhone recording, so the tone-mapping path runs.
        ffmpeg(*tone, f"testsrc2=s=640x360:r={FPS}:d=3", *tone, "sine=f=550:d=3",
               "-vf", "format=yuv420p10le,setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc",
               "-c:v", "ffv1", "-c:a", "flac", str(cls.videos / "hdr.mkv"))

        # A Cuore desktop: its theme file and its font command.
        home = tmp / "home"
        theme = home / ".local/state/cuore/current/theme"
        theme.mkdir(parents=True)
        (theme / "colors.toml").write_text('background = "#123456"\naccent = "#abcdef"\n')
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        (bin_dir / "cuore").write_text("#!/bin/sh\necho 'Test Mono'\n")
        (bin_dir / "cuore").chmod(0o755)
        # A stand-in whisper.cpp: notes what it was given, prints progress, answers like whisper-cli -oj.
        cls.fake_whisper_log = tmp / "whisper-heard.json"
        (bin_dir / "whisper-cli").write_text(f"""#!{sys.executable}
import json, sys, wave
a = sys.argv
wav, out = a[a.index("-f") + 1], a[a.index("-of") + 1]
with wave.open(wav) as w:
    heard = {{"rate": w.getframerate(), "channels": w.getnchannels(), "seconds": w.getnframes() / w.getframerate()}}
open({str(cls.fake_whisper_log)!r}, "w").write(json.dumps(heard))
for p in (0, 50, 100):
    print(f"whisper_print_progress_callback: progress = {{p}}%", file=sys.stderr)
words = [(100, 400, " Hello"), (450, 900, " there."), (2000, 2500, " [Music]")]
try:
    words = json.load(open({str(tmp / "whisper-words.json")!r}))
except OSError:
    pass
json.dump({{"transcription": [{{"offsets": {{"from": f, "to": t}}, "text": w}} for f, t, w in words]}}, open(out + ".json", "w"))
""")
        (bin_dir / "whisper-cli").chmod(0o755)
        cls.whisper_words = tmp / "whisper-words.json"
        # A stand-in Claude Code: notes how it was called, answers with picks to check.
        cls.fake_claude_log = tmp / "claude-heard.json"
        (bin_dir / "claude").write_text(f"""#!{sys.executable}
import json, sys
open({str(cls.fake_claude_log)!r}, "w").write(json.dumps({{"args": sys.argv[1:], "prompt": sys.stdin.read()}}))
picks = [{{"start": 2.0, "end": 24.0, "title": "The one trick", "why": "hook"}},
         {{"start": 500, "end": 520, "title": "not in the video", "why": "x"}},
         {{"start": 3.0, "end": 20.0, "title": "overlaps the first", "why": "x"}}]
print(json.dumps({{"type": "result", "is_error": False, "structured_output": {{"picks": picks}}}}))
""")
        (bin_dir / "claude").chmod(0o755)
        models = tmp / "data" / "cutline" / "models"
        models.mkdir(parents=True)
        (models / "ggml-test.bin").write_bytes(b"0" * (2 << 20))
        env = {**os.environ, "XDG_DATA_HOME": str(tmp / "data"), "XDG_CACHE_HOME": str(tmp / "cache"),
               "CUTLINE_VIDEOS": str(cls.videos), "CUTLINE_NO_BROWSER": "1", "PYTHONDONTWRITEBYTECODE": "1",
               "CUTLINE_DOWNLOADS": str(tmp / "Downloads"), "CUTLINE_PICTURES": str(tmp / "Pictures"),
               "HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        cls.server = subprocess.Popen([sys.executable, str(ROOT / "cutline")], env=env,
                                      stdout=subprocess.PIPE, text=True)
        cls.launch = re.search(r"http://\S+", cls.server.stdout.readline()).group(0)
        cls.base = cls.launch.split("?")[0]
        cls.browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        cls.browser.open(cls.launch, timeout=10).read()      # the window's first request: key -> cookie

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(10)
        cls.server.stdout.close()
        cls.tmp.cleanup()

    def call(self, path, body=None, *, stranger=False, headers=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path.lstrip("/"), data=data, headers=headers or {},
                                     method="POST" if data is not None else "GET")
        opener = urllib.request.build_opener() if stranger else self.browser
        try:
            with opener.open(req, timeout=30) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read()

    def json(self, path, body=None):
        status, data = self.call(path, body)
        self.assertEqual(status, 200, data)
        return json.loads(data)

    def export(self, project, scale1080=False):
        self.json("/api/export", {"project": project, "scale1080": scale1080})
        deadline = time.time() + 180
        while (state := self.json("/api/export"))["state"] == "running":
            self.assertLess(time.time(), deadline, "export took too long")
            time.sleep(0.5)
        return state

    # ---- tests ----

    def test_0_follows_the_cuore_theme_and_font(self):
        theme = self.json("/api/theme")
        self.assertEqual(theme["colors"]["background"], "#123456")
        self.assertEqual(theme["colors"]["accent"], "#abcdef")
        self.assertEqual(theme["colors"]["green"], "#9ece6a")     # the rest stay Tokyo Night
        self.assertEqual(theme["font"], "Test Mono")

    def test_1_refuses_anyone_but_its_window(self):
        self.assertEqual(self.call("/api/home", stranger=True)[0], 403)
        self.assertEqual(self.call("/api/new", {}, stranger=True)[0], 403)
        self.assertEqual(self.call(self.launch.replace(self.base, "/"), stranger=True)[0], 403,
                         "the launch key must only work once")
        self.assertEqual(self.call("/api/close", {}, headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.call("/api/home", headers={"Host": "evil.example"})[0], 403)
        status, page = self.call("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Cutline", page)

    def test_2_rejects_malformed_requests(self):
        self.assertEqual(self.call("/api/new", raw=b"[1]")[0], 400)
        self.assertEqual(self.call("/api/new", raw=b"{nope")[0], 400)
        self.assertEqual(self.call("/api/openproject", {"file": "/etc/passwd"})[0], 400)
        outside = self.videos.parent / "outside.json"           # not in the projects folder
        outside.write_text("{}")
        for path in (outside, f"{self.videos.parent}/data/cutline/projects/../../../outside.json"):
            self.call("/api/deleteproject", {"file": str(path)})
            self.assertTrue(outside.exists(), f"deleted a file outside the projects folder via {path}")

    def test_3_lists_videos(self):
        home = self.json("/api/home")
        self.assertEqual(sorted(v["name"] for v in home["videos"]), ["hdr.mkv", "mono.mp4", "sdr.mp4"])
        self.assertEqual(home["videosDir"], str(self.videos))

    def test_4_edit_and_export(self):
        self.json("/api/new", {"path": str(self.videos / "sdr.mp4")})
        for name in ("hdr.mkv", "mono.mp4"):
            self.json("/api/addsource", {"path": str(self.videos / name)})
        deadline = time.time() + 120
        while True:
            d = self.json("/api/project")
            if all(s["spriteReady"] and s["peaksReady"] and s["proxyReady"] for s in d["sources"].values()):
                break
            self.assertLess(time.time(), deadline, "thumbnails, waveforms and proxies never finished")
            time.sleep(1)
        ids = {s["name"]: sid for sid, s in d["sources"].items()}
        self.assertTrue(d["sources"][ids["hdr.mkv"]]["hdr"])

        project = d["project"]
        project["sources"] = [{"id": sid, "path": s["path"]} for sid, s in d["sources"].items()]
        project["clips"] = [   # V1: sdr, hdr at half volume, a 0.5 s gap, mono; V2: sdr in a corner
            {"id": 1, "src": ids["sdr.mp4"], "track": 1, "start": 0, "in": 0, "out": 2, "layout": "full", "size": 0.3},
            {"id": 2, "src": ids["hdr.mkv"], "track": 1, "start": 2, "in": 0.5, "out": 2.5, "layout": "full",
             "size": 0.3, "volume": 0.5},
            {"id": 3, "src": ids["mono.mp4"], "track": 1, "start": 4.5, "in": 0, "out": 1.5, "layout": "full",
             "size": 0.3},
            {"id": 4, "src": ids["sdr.mp4"], "track": 2, "start": 1, "in": 1, "out": 3, "layout": "br", "size": 0.3},
        ]
        self.json("/api/project", project)
        type(self).project = project

        state = self.export(project)
        self.assertEqual(state["state"], "done", state["error"])
        out = Path(state["output"])
        self.assertEqual(out, self.videos / "sdr-edit.mp4")
        info = probe(out)
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
        self.assertEqual(int(video["nb_read_frames"]), 6 * FPS, "every clip snapped to whole frames")
        self.assertEqual(video["color_transfer"], "bt709")
        self.assertEqual(audio["channels"], 2)
        self.assertAlmostEqual(float(info["format"]["duration"]), 6.0, delta=0.05)

    def test_5_cancel_then_export_again(self):
        self.json("/api/export", {"project": self.project})
        self.json("/api/export/cancel", {})
        state = self.export(self.project)
        self.assertEqual(state["state"], "done", state["error"])
        self.assertTrue(Path(state["output"]).is_file(), "the new export must survive the cancelled one")

    def test_6_export_stays_next_to_the_video(self):
        evil = {**self.project, "name": "../../escaped"}
        state = self.export(evil)
        self.assertEqual(state["state"], "done", state["error"])
        self.assertEqual(Path(state["output"]).parent, self.videos)
        Path(state["output"]).unlink()

    def test_7_export_rejects_bad_project_data(self):
        for bad in ({"canvas": {**self.project["canvas"], "fps": "30,drawtext=text=x"}},
                    {"canvas": {**self.project["canvas"], "w": "1920:x"}},
                    {"clips": [{**self.project["clips"][0], "start": "0,evil"}]},
                    {"tracks": "nope"}):
            self.json("/api/export", {"project": {**self.project, **bad}})
            state = self.json("/api/export")
            self.assertEqual(state["state"], "error", bad)
            self.assertIn("damaged", state["error"])

    def test_8_byte_ranges(self):
        sid = next(iter(self.json("/api/project")["sources"]))
        status, data = self.call(f"/media/{sid}", headers={"Range": "bytes=0-99"})
        self.assertEqual((status, len(data)), (206, 100))
        self.assertEqual(self.call(f"/media/{sid}", headers={"Range": "bytes=500-100"})[0], 416)

    def test_9_turned_phone_video_gets_a_landscape_canvas(self):
        # Stored portrait and tagged to play a quarter turn round, as phones do.
        plain, turned = self.videos / "plain.mp4", self.videos / "turned.mp4"
        ffmpeg("-f", "lavfi", "-i", f"testsrc2=s=360x640:r={FPS}:d=1",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", str(plain))
        ffmpeg("-display_rotation:v:0", "-90", "-i", str(plain), "-c", "copy", str(turned))
        self.json("/api/new", {"path": str(turned)})
        canvas = self.json("/api/project")["project"]["canvas"]
        self.assertEqual((canvas["w"], canvas["h"]), (640, 360))

    def test_9a_music_on_its_own_track(self):
        ffmpeg("-f", "lavfi", "-i", "sine=f=880:d=2", "-c:a", "aac", str(self.videos / "music.m4a"))
        # The editor's picker offers it; the start screen, which begins from a video, doesn't.
        self.assertIn("music.m4a", [v["name"] for v in self.json("/api/videos")["videos"]])
        self.assertNotIn("music.m4a", [v["name"] for v in self.json("/api/home")["videos"]])
        status, data = self.call("/api/new", {"path": str(self.videos / "music.m4a")})
        self.assertNotEqual(status, 200)
        self.assertIn("Start a project from a video", json.loads(data)["error"])

        self.json("/api/new", {"path": str(self.videos / "sdr.mp4")})
        music = self.json("/api/addsource", {"path": str(self.videos / "music.m4a")})
        self.assertFalse(music["video"])
        self.assertTrue(music["proxyReady"] and music["spriteReady"], "nothing to prepare without a picture")
        d = self.json("/api/project")
        ids = {s["name"]: sid for sid, s in d["sources"].items()}
        project = d["project"]
        project["sources"] = [{"id": sid, "path": s["path"]} for sid, s in d["sources"].items()]
        project["tracks"][0]["muted"] = True                 # only the music should be heard
        project["clips"] = [
            {"id": 1, "src": ids["sdr.mp4"], "track": 1, "start": 0, "in": 0, "out": 2, "layout": "full", "size": 0.3},
            {"id": 2, "src": ids["music.m4a"], "track": 2, "start": 0, "in": 0, "out": 2, "layout": "full", "size": 0.3},
        ]
        self.json("/api/project", project)
        state = self.export(project)
        self.assertEqual(state["state"], "done", state["error"])
        info = probe(state["output"])
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual(int(video["nb_read_frames"]), 2 * FPS, "the music adds sound, not picture")
        level = subprocess.run(["ffmpeg", "-i", state["output"], "-af", "volumedetect", "-f", "null", "-"],
                               capture_output=True, text=True).stderr
        mean = float(re.search(r"mean_volume: (-?[\d.]+) dB", level).group(1))
        self.assertGreater(mean, -30, "the music is in the mix")

    def test_9c_text_on_top(self):
        ffmpeg("-f", "lavfi", "-i", f"color=c=gray:s=640x360:r={FPS}:d=2",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.videos / "gray.mp4"))
        self.json("/api/new", {"path": str(self.videos / "gray.mp4")})
        d = self.json("/api/project")
        project = d["project"]
        project["clips"].append(   # quotes, colons, % and brackets must reach the picture as typed
            {"id": 2, "kind": "text", "src": "", "track": 2, "start": 0, "in": 0, "out": 1,
             "text": "It's 100%: done; [x]\nline two", "x": 0.5, "y": 0.5, "tsize": 0.12,
             "color": "#ffffff", "bg": True})
        self.json("/api/project", project)
        state = self.export(project)
        self.assertEqual(state["state"], "done", state["error"])
        W, H = 640, 360

        def frame_at(sec):
            return subprocess.run(["ffmpeg", "-v", "error", "-ss", str(sec), "-i", state["output"], "-frames:v", "1",
                                   "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout

        def off_grey(img, x0, y0, w, h):    # mean distance from the background's grey
            vals = [img[y * W + x] for y in range(y0, y0 + h) for x in range(x0, x0 + w)]
            return sum(abs(v - 128) for v in vals) / len(vals)

        during, after = frame_at(0.5), frame_at(1.5)
        self.assertGreater(off_grey(during, W // 2 - 120, H // 2 - 30, 240, 60), 30, "the text and its box are drawn")
        self.assertLess(off_grey(during, 0, 0, 40, 40), 8, "the rest of the picture is untouched")
        self.assertLess(off_grey(after, W // 2 - 120, H // 2 - 30, 240, 60), 8, "the text ends with its clip")

    def test_9d_fades_and_fonts(self):
        self.json("/api/new", {"path": str(self.videos / "gray.mp4")})        # made by test_9c
        music = self.json("/api/addsource", {"path": str(self.videos / "music.m4a")})   # made by test_9a
        d = self.json("/api/project")
        project = d["project"]
        project["sources"] = [{"id": sid, "path": s["path"]} for sid, s in d["sources"].items()]
        project["tracks"] = [{"id": i, "name": f"V{i}", "hidden": False, "muted": i == 1} for i in (1, 2, 3)]
        project["clips"] += [
            {"id": 2, "kind": "text", "src": "", "track": 2, "start": 0, "in": 0, "out": 2, "text": "FADE",
             "x": 0.5, "y": 0.5, "tsize": 0.2, "color": "#ffffff", "bg": True, "font": "Liberation Serif",
             "bold": False, "fadeIn": 1, "fadeOut": 0.5},
            # an unknown font name falls back to the default rather than reaching fontconfig
            {"id": 3, "kind": "text", "src": "", "track": 2, "start": 2, "in": 0, "out": 0.1, "text": "x",
             "x": 0.5, "y": 0.5, "tsize": 0.05, "color": "#ffffff", "bg": False, "font": "Nope:weight=1,-x"},
            {"id": 4, "src": music["id"], "track": 3, "start": 0, "in": 0, "out": 2, "layout": "full", "size": 0.3,
             "fadeIn": 1},
        ]
        self.json("/api/project", project)
        state = self.export(project)
        self.assertEqual(state["state"], "done", state["error"])
        W, H = 640, 360

        def grey_at(sec):
            img = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(sec), "-i", state["output"], "-frames:v", "1",
                                  "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
            vals = [img[y * W + x] for y in range(H // 2 - 40, H // 2 + 40) for x in range(W // 2 - 120, W // 2 + 120)]
            return sum(abs(v - 128) for v in vals) / len(vals)

        self.assertLess(grey_at(0.05), 8, "the text starts faded out")
        self.assertGreater(grey_at(1.2), 25, "and is fully there after its fade-in")
        self.assertLess(grey_at(1.95), grey_at(1.2) / 2, "and fades out at the end")

        def loudness(start, dur):
            err = subprocess.run(["ffmpeg", "-ss", str(start), "-t", str(dur), "-i", state["output"],
                                  "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True).stderr
            return float(re.search(r"mean_volume: (-?[\d.]+) dB", err).group(1))

        self.assertLess(loudness(0, 0.2), loudness(1.2, 0.3) - 10, "the music fades in")

    def test_9b_three_portrait_clips_side_by_side(self):
        # Three portrait clips in a landscape canvas, each filling a third, as "Side by side" sets them.
        colours = {"red": (255, 0, 0), "lime": (0, 255, 0), "blue": (0, 0, 255)}
        for name in colours:
            ffmpeg("-f", "lavfi", "-i", f"color=c={name}:s=360x640:r={FPS}:d=1",
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.videos / f"{name}.mp4"))
        self.json("/api/new", {"path": str(self.videos / "sdr.mp4")})      # a 640x360 canvas
        for name in colours:
            self.json("/api/addsource", {"path": str(self.videos / f"{name}.mp4")})
        d = self.json("/api/project")
        ids = {s["name"]: sid for sid, s in d["sources"].items()}
        project = d["project"]
        project["sources"] = [{"id": sid, "path": s["path"]} for sid, s in d["sources"].items()]
        project["tracks"] = [{"id": i, "name": f"V{i}", "hidden": False, "muted": False} for i in (1, 2, 3)]
        project["clips"] = [
            {"id": i, "src": ids[f"{name}.mp4"], "track": i, "start": 0, "in": 0, "out": 1, "layout": "free",
             "fit": "fill", "box": {"x": (i - 1) / 3, "y": 0, "w": 1 / 3, "h": 1}, "size": 0.3}
            for i, name in enumerate(colours, 1)]
        self.json("/api/project", project)

        state = self.export(project)
        self.assertEqual(state["state"], "done", state["error"])
        W, H = 640, 360
        rgb = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", state["output"], "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        self.assertEqual(len(rgb), W * H * 3)

        def pixel(x, y):
            return rgb[(y * W + x) * 3:(y * W + x) * 3 + 3]

        for third, want in enumerate(colours.values()):
            # the middle and the corners of each column: filled, so no black bars anywhere
            for x, y in ((third * W // 3 + W // 6, H // 2), (third * W // 3 + 4, 4),
                         ((third + 1) * W // 3 - 5, H - 5)):
                got = pixel(x, y)
                self.assertTrue(all(abs(g - w) < 70 for g, w in zip(got, want, strict=True)),
                                f"pixel {x},{y} is {tuple(got)}, wanted about {want}")

    def test_9e_many_cuts_export_in_pieces(self):
        # Like a long talking-head edit: a side-by-side opener on V1, then dozens of cuts on V2.
        # The export renders this in pieces and joins them; every frame must land where it was.
        colours = {"lime": (0, 255, 0), "red": (255, 0, 0), "blue": (0, 0, 255)}
        for name in colours:
            ffmpeg("-f", "lavfi", "-i", f"color=c={name}:s=640x360:r={FPS}:d=1",
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.videos / f"cut-{name}.mp4"))
        self.json("/api/new", {"path": str(self.videos / "sdr.mp4")})
        for name in colours:
            self.json("/api/addsource", {"path": str(self.videos / f"cut-{name}.mp4")})
        d = self.json("/api/project")
        ids = {s["name"]: sid for sid, s in d["sources"].items()}
        project = d["project"]
        project["sources"] = [{"id": sid, "path": s["path"]} for sid, s in d["sources"].items()]
        project["tracks"] = [{"id": i, "name": f"V{i}", "hidden": False, "muted": False} for i in (1, 2)]
        cuts = 24
        project["clips"] = [{"id": 1, "src": ids["cut-lime.mp4"], "track": 1, "start": 0, "in": 0, "out": 1,
                             "layout": "free", "fit": "fill", "box": {"x": 0, "y": 0, "w": 0.5, "h": 1}, "size": 0.3}]
        project["clips"] += [{"id": 2 + i, "src": ids[f"cut-{'blue' if i % 2 else 'red'}.mp4"], "track": 2,
                              "start": 1 + i / 2, "in": 0, "out": 0.5, "layout": "full", "size": 0.3}
                             for i in range(cuts)]
        self.json("/api/project", project)

        state = self.export(project)
        self.assertEqual(state["state"], "done", state["error"])
        info = probe(state["output"])
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
        total = 1 + cuts / 2
        self.assertEqual(int(video["nb_read_frames"]), total * FPS, "the pieces add up to every frame")
        self.assertAlmostEqual(float(info["format"]["duration"]), total, delta=0.05)
        self.assertEqual(audio["channels"], 2)

        def colour_at(t):
            return subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", state["output"], "-frames:v", "1",
                                   "-vf", "crop=2:2:160:180", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                  capture_output=True, check=True).stdout[:3]

        for t, want in ((0.5, colours["lime"]), (1.25, colours["red"]), (1.75, colours["blue"]),
                        (total - 0.75, colours["red"]), (total - 0.25, colours["blue"])):
            got = colour_at(t)
            self.assertTrue(all(abs(g - w) < 70 for g, w in zip(got, want, strict=True)),
                            f"at {t}s the picture is {tuple(got)}, wanted about {want}")

    def test_9f_crop_turn_and_detached_sound(self):
        # A picture that is red on the left half and blue on the right.
        ffmpeg("-f", "lavfi", "-i", f"color=c=red:s=640x360:r={FPS}:d=1", "-f", "lavfi", "-i",
               f"color=c=blue:s=320x360:r={FPS}:d=1", "-filter_complex", "[0][1]overlay=x=320",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.videos / "halves.mp4"))
        self.json("/api/new", {"path": str(self.videos / "halves.mp4")})
        self.json("/api/addsource", {"path": str(self.videos / "sdr.mp4")})
        d = self.json("/api/project")
        ids = {s["name"]: sid for sid, s in d["sources"].items()}
        project = d["project"]
        project["sources"] = [{"id": sid, "path": s["path"]} for sid, s in d["sources"].items()]
        project["tracks"] = [{"id": i, "name": f"V{i}", "hidden": False, "muted": False} for i in (1, 2)]
        halves = {"src": ids["halves.mp4"], "track": 1, "in": 0, "out": 1, "layout": "full", "size": 0.3}
        project["clips"] = [
            {**halves, "id": 1, "start": 0, "crop": {"l": 0.5, "t": 0, "r": 0, "b": 0}},   # only the blue half
            {**halves, "id": 2, "start": 1, "rotate": 90},                                # red on top, blue below
            # sdr.mp4's sound only, detached from its picture: it must add sound and no picture
            {"id": 3, "src": ids["sdr.mp4"], "track": 2, "start": 0, "in": 0, "out": 2, "layout": "full",
             "size": 0.3, "audioOnly": True},
        ]
        self.json("/api/project", project)

        state = self.export(project)
        self.assertEqual(state["state"], "done", state["error"])
        W, H = 640, 360

        def pixel(t, x, y):
            rgb = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", state["output"], "-frames:v", "1",
                                  "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
            return rgb[(y * W + x) * 3:(y * W + x) * 3 + 3]

        red, blue, black = (255, 0, 0), (0, 0, 255), (0, 0, 0)
        for t, x, y, want, why in ((0.5, W // 2, H // 2, blue, "the cropped clip shows the blue half"),
                                   (0.5, 20, H // 2, black, "the cropped half-width picture has bars beside it"),
                                   (1.5, W // 2, 60, red, "turned clockwise, the left half is on top"),
                                   (1.5, W // 2, H - 60, blue, "turned clockwise, the right half is below")):
            got = pixel(t, x, y)
            self.assertTrue(all(abs(g - w) < 70 for g, w in zip(got, want, strict=True)),
                            f"{why}: pixel {x},{y} at {t}s is {tuple(got)}, wanted about {want}")
        level = subprocess.run(["ffmpeg", "-i", state["output"], "-af", "volumedetect", "-f", "null", "-"],
                               capture_output=True, text=True).stderr
        self.assertGreater(float(re.search(r"mean_volume: (-?[\d.]+) dB", level).group(1)), -30,
                           "the detached sound is in the mix")

    def test_9g_tall_canvas_bars_gif_and_loudness(self):
        ffmpeg("-f", "lavfi", "-i", f"color=c=red:s=640x360:r={FPS}:d=2", "-f", "lavfi", "-i",
               f"color=c=blue:s=320x360:r={FPS}:d=2", "-f", "lavfi", "-i", "sine=f=440:d=2,volume=0.03",
               "-filter_complex", "[0][1]overlay=x=320", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-c:a", "aac", str(self.videos / "quiet.mp4"))
        self.json("/api/new", {"path": str(self.videos / "quiet.mp4")})
        d = self.json("/api/project")
        sid = next(sid for sid, s in d["sources"].items() if s["name"] == "quiet.mp4")
        project = d["project"]
        project["canvas"] = {**project["canvas"], "w": 360, "h": 640}          # 9:16, as the switcher sets it
        clip = {"id": 1, "src": sid, "track": 1, "start": 0, "in": 0, "out": 1, "layout": "full", "size": 0.3}
        W, H = 360, 640

        def export(clips, **options):
            self.json("/api/project", {**project, "clips": clips})
            self.json("/api/export", {"project": {**project, "clips": clips}, **options})
            deadline = time.time() + 120
            while (state := self.json("/api/export"))["state"] == "running":
                self.assertLess(time.time(), deadline, "export took too long")
                time.sleep(0.3)
            self.assertEqual(state["state"], "done", state["error"])
            return state["output"]

        def pixel(out, x, y):
            rgb = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", out, "-frames:v", "1",
                                  "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
            return tuple(rgb[(y * W + x) * 3:(y * W + x) * 3 + 3])

        near = lambda got, want: all(abs(g - w) < 70 for g, w in zip(got, want, strict=True))
        # Fill: the wide picture covers the tall canvas, cut evenly at the sides (red left, blue right).
        out = export([{**clip, "fit": "fill"}])
        self.assertTrue(near(pixel(out, 20, H // 2), (255, 0, 0)) and near(pixel(out, W - 20, H // 2), (0, 0, 255)),
                        "Fill covers the canvas from the middle of the picture")
        # Black bars above and below by default; blurred bars fill them with the picture's colours.
        out = export([clip])
        self.assertTrue(near(pixel(out, 20, 40), (0, 0, 0)), "black bars by default")
        out = export([{**clip, "bars": "blur"}])
        top = pixel(out, 20, 40)
        self.assertGreater(sum(top), 120, f"blurred bars aren't black: {top}")
        self.assertTrue(near(pixel(out, 20, H // 2), (255, 0, 0)), "the picture itself stays sharp in the middle")
        # GIF: picture only, its own palette, 15 frames a second.
        out = export([clip], preset="gif")
        self.assertTrue(out.endswith(".gif"))
        gif = probe(out)["streams"]
        self.assertEqual([s["codec_name"] for s in gif], ["gif"])
        self.assertEqual(int(gif[0]["nb_read_frames"]), 15)
        # Loudness: a very quiet clip comes out at about -14 LUFS.
        out = export([{**clip, "out": 2}], loudness=True)
        report = subprocess.run(["ffmpeg", "-nostats", "-i", out, "-af", "ebur128", "-f", "null", "-"],
                                capture_output=True, text=True).stderr
        lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", report)[-1])
        self.assertAlmostEqual(lufs, -14, delta=1.5, msg=f"integrated loudness {lufs} LUFS")
    def test_9h_text_looks_and_typewriter(self):
        ffmpeg("-f", "lavfi", "-i", f"color=c=gray:s=640x360:r={FPS}:d=4",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.videos / "plain.mp4"))
        self.json("/api/new", {"path": str(self.videos / "plain.mp4")})
        d = self.json("/api/project")
        project = d["project"]
        project["tracks"] = [{"id": i, "name": f"V{i}", "hidden": False, "muted": False} for i in (1, 2, 3, 4)]
        text = {"kind": "text", "src": "", "in": 0, "x": 0.5, "tsize": 0.2, "color": "#ffffff", "bg": False}
        project["clips"] = [project["clips"][0],
            {**text, "id": 2, "track": 2, "start": 0, "out": 4, "y": 0.2, "text": "MMMM", "outline": 0.15, "outlineColor": "#ff0000"},
            {**text, "id": 3, "track": 3, "start": 0, "out": 4, "y": 0.8, "text": "GLOW", "color": "#000000",
             "glow": 1, "glowColor": "#00ff00"},
            {**text, "id": 4, "track": 4, "start": 0, "out": 3, "y": 0.5, "tsize": 0.12, "text": "ABCDEFGHIJ",
             "animIn": "type", "fadeIn": 2},
            {**text, "id": 5, "track": 4, "start": 3, "out": 1, "y": 0.5, "tsize": 0.1, "text": "left", "x": 0.1,
             "align": "L", "bg": True, "boxColor": "#0000ff", "boxOpacity": 1, "fadeIn": 0, "animIn": "none"}]
        self.json("/api/project", project)
        state = self.export(project)
        self.assertEqual(state["state"], "done", state["error"])
        W, H = 640, 360

        def frame(t):
            return subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", state["output"], "-frames:v", "1",
                                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout

        def count(rgb, rows, want):
            px = (rgb[(y * W + x) * 3:(y * W + x) * 3 + 3] for y in range(*rows) for x in range(W))
            return sum(all(abs(c - w) < 70 for c, w in zip(p, want, strict=True)) for p in px)

        late = frame(2.5)
        self.assertGreater(count(late, (0, H // 3), (255, 0, 0)), 400, "a red outline round the top text")
        self.assertGreater(count(late, (2 * H // 3, H), (0, 255, 0)), 400, "a green glow round the bottom text")
        typed_early, typed_late = count(frame(0.3), (H // 3, 2 * H // 3), (255, 255, 255)), \
            count(late, (H // 3, 2 * H // 3), (255, 255, 255))
        self.assertGreater(typed_late, 2 * typed_early, f"the typewriter shows more later ({typed_early} → {typed_late})")
        self.assertGreater(typed_early, 0, "and something from the start")
        boxed = frame(3.5)

        def pixel(x, y):
            return boxed[(y * W + x) * 3:(y * W + x) * 3 + 3]

        self.assertTrue(all(abs(c - w) < 70 for c, w in zip(pixel(58, H // 2), (0, 0, 255), strict=True)),
                        "a left-aligned title starts at its spot (its box padding just left of x=64)")
        self.assertTrue(all(abs(c - 128) < 40 for c in pixel(30, H // 2)), "and nothing to its left")

    def test_9i_pictures_stickers_and_gifs(self):
        # A sticker: transparent, with a yellow box in the middle. Dropped on the window (uploaded).
        sticker = self.downloads / "sticker.png"
        ffmpeg("-f", "lavfi", "-i", "color=c=black@0:s=200x100,format=rgba,drawbox=x=50:y=25:w=100:h=50:color=yellow@1:t=fill:replace=1",
               "-frames:v", "1", str(sticker))
        # An animated GIF of 1.5 s: lime then blue.
        gif = self.downloads / "flash.gif"
        ffmpeg("-f", "lavfi", "-i", "color=c=lime:s=160x120:r=10:d=0.75", "-f", "lavfi", "-i",
               "color=c=blue:s=160x120:r=10:d=0.75", "-filter_complex", "[0][1]concat=n=2:v=1", str(gif))
        ffmpeg("-f", "lavfi", "-i", f"color=c=red:s=640x360:r={FPS}:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               str(self.videos / "redbg.mp4"))
        self.json("/api/new", {"path": str(self.videos / "redbg.mp4")})

        drawer = self.json("/api/drawer")["files"]
        self.assertEqual({f["name"]: f["kind"] for f in drawer}, {"sticker.png": "image", "flash.gif": "gif"})
        status, data = self.call(f"/api/thumb?path={sticker}")
        self.assertEqual((status, data[:4]), (200, b"\x89PNG"), "the drawer shows the sticker")
        self.assertEqual(self.call("/api/thumb?path=/etc/passwd")[0], 404, "and nothing outside its folders")

        status, data = self.call("/api/upload?name=sticker.png", raw=sticker.read_bytes())
        self.assertEqual(status, 200, data)
        up = json.loads(data)
        self.assertTrue(up["image"] and up["still"] and up["alpha"], up)
        self.assertEqual(Path(up["path"]).parent, self.videos / "Cutline media", "kept in the media folder")
        anim = self.json("/api/addsource", {"path": str(gif)})
        self.assertTrue(anim["loop"] and not anim["still"])
        self.assertAlmostEqual(anim["duration"], 1.5, delta=0.11)
        deadline = time.time() + 60
        while not all(self.json(f"/api/source/{s['id']}")["proxyReady"] for s in (up, anim)):
            self.assertLess(time.time(), deadline, "the pictures' preview copies never finished")
            time.sleep(0.5)

        status, data = self.call("/api/fetch", {"url": "http://127.0.0.1:1/x.gif"})
        self.assertEqual(status, 400)
        self.assertIn("internet", json.loads(data)["error"], "never fetches from this computer")
        self.assertEqual(self.call("/api/openweb", {"site": "evil"})[0], 400)
        status, data = self.call("/api/new", {"path": str(sticker)})
        self.assertEqual(status, 400, "a project starts from a video")

        d = self.json("/api/project")
        project = d["project"]
        project["sources"] = [{"id": sid, "path": s["path"]} for sid, s in d["sources"].items()]
        project["tracks"] = [{"id": i, "name": f"V{i}", "hidden": False, "muted": False} for i in (1, 2, 3)]
        bg = next(sid for sid, s in d["sources"].items() if s["name"] == "redbg.mp4")
        project["clips"] = [
            {"id": 1, "src": bg, "track": 1, "start": 0, "in": 0, "out": 4, "layout": "full", "size": 0.3},
            # the sticker over the left half, the GIF looping for 3 s in the top right corner
            {"id": 2, "src": up["id"], "track": 2, "start": 0, "in": 0, "out": 4, "layout": "free", "size": 0.3,
             "box": {"x": 0, "y": 0.25, "w": 0.5, "h": 0.5}},
            {"id": 3, "src": anim["id"], "track": 3, "start": 0, "in": 0, "out": 3, "layout": "tr", "size": 0.3}]
        self.json("/api/project", project)
        state = self.export(project)
        self.assertEqual(state["state"], "done", state["error"])
        info = probe(state["output"])
        self.assertEqual(int(next(s for s in info["streams"] if s["codec_type"] == "video")["nb_read_frames"]), 4 * FPS)
        W = 640

        def pixel(t, x, y):
            rgb = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", state["output"], "-frames:v", "1",
                                  "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
            return rgb[(y * W + x) * 3:(y * W + x) * 3 + 3]

        near = lambda got, want: all(abs(g - w) < 70 for g, w in zip(got, want, strict=True))
        self.assertTrue(near(pixel(1, 160, 180), (255, 255, 0)), "the sticker's yellow box shows")
        self.assertTrue(near(pixel(1, 20, 110), (255, 0, 0)), "and the video shows through its clear part")
        corner = (W - 40, 40)                         # inside the GIF in the top right corner
        self.assertTrue(near(pixel(0.3, *corner), (0, 255, 0)), "the GIF starts lime")
        self.assertTrue(near(pixel(1.1, *corner), (0, 0, 255)), "then turns blue")
        self.assertTrue(near(pixel(1.8, *corner), (0, 255, 0)), "and loops back to lime")
        self.assertTrue(near(pixel(3.5, *corner), (255, 0, 0)), "and is gone after its 3 seconds")
    def test_9j_speed_zoom_keys_and_transitions(self):
        v = self.videos
        # 1 s red then 1 s blue, with a tone: speed is easy to see
        ffmpeg("-f", "lavfi", "-i", f"color=c=red:s=640x360:r={FPS}:d=1", "-f", "lavfi", "-i",
               f"color=c=blue:s=640x360:r={FPS}:d=1", "-f", "lavfi", "-i", "sine=f=440:d=2",
               "-filter_complex", "[0][1]concat=n=2:v=1[v]", "-map", "[v]", "-map", "2",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(v / "redblue.mp4"))
        for name in ("red", "blue", "white"):
            ffmpeg("-f", "lavfi", "-i", f"color=c={name}:s=640x360:r={FPS}:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                   str(v / f"solid-{name}.mp4"))
        ffmpeg("-f", "lavfi", "-i", f"color=c=red:s=640x360:r={FPS}:d=3", "-f", "lavfi", "-i",
               f"color=c=blue:s=320x360:r={FPS}:d=3", "-filter_complex", "[0][1]overlay=x=320",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", str(v / "lr.mp4"))
        self.json("/api/new", {"path": str(v / "redblue.mp4")})
        for name in ("solid-red.mp4", "solid-blue.mp4", "solid-white.mp4", "lr.mp4"):
            self.json("/api/addsource", {"path": str(v / name)})
        d = self.json("/api/project")
        ids = {s["name"]: sid for sid, s in d["sources"].items()}
        project = d["project"]
        project["sources"] = [{"id": sid, "path": s["path"]} for sid, s in d["sources"].items()]
        project["tracks"] = [{"id": i, "name": f"V{i}", "hidden": False, "muted": False} for i in (1, 2)]
        W = 640
        clip = lambda i, src, start, out, **k: {"id": i, "src": ids[src], "track": 1, "start": start, "in": 0,
                                                 "out": out, "layout": "full", "size": 0.3, **k}

        def export(clips):
            state = self.export({**project, "clips": clips})
            self.assertEqual(state["state"], "done", state["error"])
            return state["output"]

        def frames_of(out):
            return int(next(s for s in probe(out)["streams"] if s["codec_type"] == "video")["nb_read_frames"])

        def pixel(out, t, x, y=180):
            rgb = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", out, "-frames:v", "1",
                                  "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
            return tuple(rgb[(y * W + x) * 3:(y * W + x) * 3 + 3])

        near = lambda got, want, tol=70: all(abs(g - w) < tol for g, w in zip(got, want, strict=True))
        red, blue, black = (255, 0, 0), (0, 0, 255), (0, 0, 0)

        # Speed: 2x makes the 2 s clip last 1 s (red half a second, then blue); 0.5x stretches it.
        out = export([clip(1, "redblue.mp4", 0, 2, speed=2)])
        self.assertEqual(frames_of(out), FPS)
        self.assertTrue(near(pixel(out, 0.25, 320), red) and near(pixel(out, 0.75, 320), blue), "2x plays twice as fast")
        audio = next(s for s in probe(out)["streams"] if s["codec_type"] == "audio")
        self.assertAlmostEqual(float(audio.get("duration") or 1), 1, delta=0.1)
        out = export([clip(1, "redblue.mp4", 0, 1, speed=0.5)])
        self.assertEqual(frames_of(out), 2 * FPS)
        self.assertTrue(near(pixel(out, 1.5, 320), red), "0.5x: still red at 1.5 s")

        # Transitions: red then blue, joined with a 1 s crossfade or a dip to black; same length.
        for kind, mid in (("fade", (128, 0, 128)), ("dip", black)):
            out = export([clip(1, "solid-red.mp4", 0, 2), clip(2, "solid-blue.mp4", 2, 2, trans={"type": kind, "dur": 1})])
            self.assertEqual(frames_of(out), 4 * FPS, f"{kind}: the timeline keeps its length")
            self.assertTrue(near(pixel(out, 1.2, 320), red) and near(pixel(out, 2.8, 320), blue), kind)
            self.assertTrue(near(pixel(out, 2.0, 320), mid, 90), f"{kind} at the cut: {pixel(out, 2.0, 320)}")

        # Zoom: 2x towards the left edge shows only the red left half; Ken Burns gets there over time.
        out = export([clip(1, "lr.mp4", 0, 2, zoom=2, fx=0, fy=0.5)])
        self.assertTrue(near(pixel(out, 1, W - 10), red), "a punch-in to the left")
        keys = [{"t": 0, "zoom": 1, "fx": 0, "fy": 0.5, "x": 0, "y": 0}, {"t": 2, "zoom": 2, "fx": 0, "fy": 0.5, "x": 0, "y": 0}]
        out = export([clip(1, "lr.mp4", 0, 2, keys=keys)])
        self.assertTrue(near(pixel(out, 0.05, W - 10), blue), "Ken Burns starts wide")
        self.assertTrue(near(pixel(out, 1.95, W - 10), red), "and ends zoomed in")

        # A small white box sliding from left to right over black, at half opacity.
        keys = [{"t": 0, "zoom": 1, "fx": 0.5, "fy": 0.5, "x": 0, "y": 0.4},
                {"t": 2, "zoom": 1, "fx": 0.5, "fy": 0.5, "x": 0.8, "y": 0.4}]
        slide = {"id": 2, "src": ids["solid-white.mp4"], "track": 2, "start": 0, "in": 0, "out": 2, "layout": "free",
                 "size": 0.3, "box": {"x": 0, "y": 0.4, "w": 0.2, "h": 0.2}, "keys": keys, "opacity": 0.5}
        out = export([clip(1, "solid-red.mp4", 0, 2, volume=0, opacity=0), slide])
        self.assertTrue(near(pixel(out, 0.02, 60), (128, 128, 128), 45), f"half-white at the left: {pixel(out, 0.02, 60)}")
        self.assertTrue(near(pixel(out, 0.02, 580), black), "nothing yet at the right")
        self.assertTrue(near(pixel(out, 1.9, 560), (128, 128, 128), 45), f"slid to the right: {pixel(out, 1.9, 560)}")
    def test_9k_colour_lut_and_green_screen(self):
        v = self.videos
        # A mid-grey picture with a pure-green square in the middle: something to colour and to key.
        ffmpeg("-f", "lavfi", "-i", f"color=c=0x808080:s=640x360:r={FPS}:d=2", "-vf",
               "drawbox=x=220:y=100:w=200:h=160:color=0x00ff00:t=fill", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               str(v / "greenbox.mp4"))
        ffmpeg("-f", "lavfi", "-i", f"color=c=red:s=640x360:r={FPS}:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               str(v / "redback.mp4"))
        # An "invert" LUT, in the LUT folder: what's dark becomes light.
        luts = v / "LUTs"
        luts.mkdir(exist_ok=True)
        rows = [f"{1 - r / 1:.1f} {1 - g / 1:.1f} {1 - b / 1:.1f}" for b in (0, 1) for g in (0, 1) for r in (0, 1)]
        (luts / "invert.cube").write_text('TITLE "invert"\nLUT_3D_SIZE 2\n' + "\n".join(rows) + "\n")
        self.json("/api/new", {"path": str(v / "greenbox.mp4")})
        self.json("/api/addsource", {"path": str(v / "redback.mp4")})
        listed = self.json("/api/luts")["luts"]
        self.assertIn("invert", [x["name"] for x in listed])
        status, data = self.call(f"/api/lut?path={luts / 'invert.cube'}")
        self.assertEqual((status, data[:5]), (200, b"TITLE"))
        self.assertEqual(self.call("/api/lut?path=/etc/passwd")[0], 404, "only .cube files from the LUT folders")

        d = self.json("/api/project")
        ids = {s["name"]: sid for sid, s in d["sources"].items()}
        project = d["project"]
        project["sources"] = [{"id": sid, "path": s["path"]} for sid, s in d["sources"].items()]
        project["tracks"] = [{"id": i, "name": f"V{i}", "hidden": False, "muted": False} for i in (1, 2)]
        grey = {"id": 1, "src": ids["greenbox.mp4"], "track": 1, "start": 0, "in": 0, "out": 2, "layout": "full", "size": 0.3}
        W = 640

        def export(clips):
            state = self.export({**project, "clips": clips})
            self.assertEqual(state["state"], "done", state["error"])
            return state["output"]

        def pixel(out, x, y):
            rgb = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", out, "-frames:v", "1",
                                  "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
            return tuple(rgb[(y * W + x) * 3:(y * W + x) * 3 + 3])

        near = lambda got, want, tol=30: all(abs(g - w) < tol for g, w in zip(got, want, strict=True))
        plain = pixel(export([grey]), 40, 40)
        bright = pixel(export([{**grey, "color": {"b": 1.5, "c": 1, "s": 1, "t": 0}}]), 40, 40)
        self.assertGreater(sum(bright), sum(plain) + 100, f"brighter: {plain} → {bright}")
        warm = pixel(export([{**grey, "color": {"b": 1, "c": 1, "s": 1, "t": 1}}]), 40, 40)
        self.assertGreater(warm[0] - warm[2], 40, f"warmer: more red than blue {warm}")
        mono = pixel(export([{**grey, "color": {"b": 1, "c": 1, "s": 0, "t": 0}}]), 320, 180)
        self.assertLess(max(mono) - min(mono), 12, f"no saturation: the green square turns grey {mono}")
        # (compared with the plain export: how pure the green comes out depends on the ffmpeg version)
        square = pixel(export([grey]), 320, 180)
        inverted = pixel(export([{**grey, "lut": str(luts / "invert.cube")}]), 320, 180)
        self.assertTrue(near(inverted, tuple(255 - x for x in square), 40), f"the LUT inverts: {square} → {inverted}")
        outside = pixel(export([{**grey, "lut": "/etc/passwd"}]), 320, 180)
        self.assertTrue(near(outside, square, 20), "a LUT from anywhere else is ignored")
        # Green screen: over a red clip, the green square becomes see-through, the grey stays.
        keyed = export([{**grey, "id": 2, "src": ids["redback.mp4"]},
                        {**grey, "track": 2, "key": {"on": True, "color": "#00ff00", "sim": 0.2, "blend": 0.05}}])
        self.assertTrue(near(pixel(keyed, 320, 180), (255, 0, 0), 50), f"red shows through: {pixel(keyed, 320, 180)}")
        self.assertTrue(near(pixel(keyed, 40, 40), (128, 128, 128), 30), "the grey isn't keyed")
    def test_9l_silences_ducking_thumbnail_and_captions(self):
        v = self.videos
        # tone, 1 s of silence, tone
        ffmpeg("-f", "lavfi", "-i", "sine=f=1000:d=1", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=1",
               "-f", "lavfi", "-i", "sine=f=1000:d=1", "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", str(v / "pause.wav"))
        ffmpeg("-f", "lavfi", "-i", f"color=c=red:s=640x360:r={FPS}:d=1", "-f", "lavfi", "-i",
               f"color=c=blue:s=640x360:r={FPS}:d=2", "-filter_complex", "[0][1]concat=n=2:v=1", "-c:v", "libx264",
               "-pix_fmt", "yuv420p", str(v / "redthenblue.mp4"))
        ffmpeg("-f", "lavfi", "-i", "sine=f=200:d=3", "-af", "volume=0.5", str(v / "music.wav"))
        self.json("/api/new", {"path": str(v / "redthenblue.mp4")})
        for name in ("pause.wav", "music.wav"):
            self.json("/api/addsource", {"path": str(v / name)})
        d = self.json("/api/project")
        ids = {s["name"]: sid for sid, s in d["sources"].items()}

        found = self.json("/api/silences", {"src": ids["pause.wav"], "in": 0, "out": 3, "noise": -40, "least": 0.4})["silences"]
        self.assertEqual(len(found), 1, found)
        self.assertAlmostEqual(found[0][0], 1, delta=0.1)
        self.assertAlmostEqual(found[0][1], 2, delta=0.1)

        project = d["project"]
        project["sources"] = [{"id": sid, "path": s["path"]} for sid, s in d["sources"].items()]
        project["tracks"] = [{"id": i, "name": f"V{i}", "hidden": False, "muted": False} for i in (1, 2, 3)]
        picture = {"id": 1, "src": ids["redthenblue.mp4"], "track": 1, "start": 0, "in": 0, "out": 3, "layout": "full", "size": 0.3}
        voice = {"id": 2, "src": ids["pause.wav"], "track": 2, "start": 0, "in": 0, "out": 3, "layout": "full", "size": 0.3}
        music = {"id": 3, "src": ids["music.wav"], "track": 3, "start": 0, "in": 0, "out": 3, "layout": "full", "size": 0.3}

        def music_level(out, start):              # how loud the 200 Hz music is over 0.6 s
            stats = subprocess.run(["ffmpeg", "-ss", f"{start}", "-t", "0.6", "-i", out, "-af",
                                    "lowpass=f=300,lowpass=f=300,astats=metadata=0", "-f", "null", "-"],
                                   capture_output=True, text=True).stderr
            return float(re.findall(r"RMS level dB: (-?[\d.]+|-inf)", stats)[-1])

        plain = self.export({**project, "clips": [picture, voice, music]})
        ducked = self.export({**project, "clips": [picture, voice, {**music, "duck": True}]})
        for state in (plain, ducked):
            self.assertEqual(state["state"], "done", state["error"])
        quiet_part, talking = music_level(ducked["output"], 1.2), music_level(ducked["output"], 0.2)
        self.assertGreater(quiet_part - talking, 6, f"ducked: {talking} dB while talking, {quiet_part} dB in the pause")
        self.assertLess(abs(music_level(plain["output"], 0.2) - music_level(plain["output"], 1.2)), 2, "not ducked: steady")

        # The thumbnail: the frame at 1.5 s (blue), as a PNG
        self.json("/api/export", {"project": {**project, "clips": [picture]}, "frameAt": 1.5})
        deadline = time.time() + 60
        while (state := self.json("/api/export"))["state"] == "running":
            self.assertLess(time.time(), deadline)
            time.sleep(0.3)
        self.assertEqual((state["state"], state["kind"]), ("done", "thumbnail"), state["error"])
        self.assertTrue(state["output"].endswith("-thumbnail.png"))
        rgb = subprocess.run(["ffmpeg", "-v", "error", "-i", state["output"], "-vf", "crop=1:1:320:180", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        self.assertTrue(rgb[2] > 200 and rgb[0] < 60, f"the frame at 1.5 s is blue: {tuple(rgb)}")

        # Captions, with a stand-in whisper.cpp (the real one is checked by hand): it has to get a
        # 16 kHz mono file of the voices and answer with words and their times.
        status = self.json("/api/captions")
        self.assertTrue(status["whisper"] and status["models"], status)
        self.json("/api/captions", {"project": {**project, "clips": [picture, voice, {**music, "duck": True}]}})
        deadline = time.time() + 60
        while (state := self.json("/api/export"))["state"] == "running":
            self.assertLess(time.time(), deadline)
            time.sleep(0.3)
        self.assertEqual(state["state"], "done", state["error"])
        self.assertEqual([w["w"] for w in state["result"]], ["Hello", "there."], "[Music] is left out")
        self.assertEqual(state["result"][0]["t0"], 0.1)
        heard = json.loads((self.fake_whisper_log).read_text())
        self.assertEqual((heard["rate"], heard["channels"]), (16000, 1))
        self.assertAlmostEqual(heard["seconds"], 3, delta=0.1)

    def test_9m_auto_shorts(self):
        v = self.videos
        ffmpeg("-f", "lavfi", "-i", f"testsrc2=s=640x360:r={FPS}:d=40", "-f", "lavfi", "-i", "sine=f=300:d=40",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(v / "talk.mp4"))
        # 40 s of "speech": a sentence every 2 s (with a 1 s pause before 12 s), whose words fill 1.5 s each
        words = []
        for s in range(20):
            base = s * 2000 + (1000 if s >= 6 else 0)
            for k, w in enumerate(["This", "is", "sentence", f"{s}."] if s else ["How", "does", "this", "work?"]):
                words.append([base + k * 375, base + k * 375 + 350, " " + w])
        self.whisper_words.write_text(json.dumps([w for w in words if w[1] <= 40000]))
        self.json("/api/new", {"path": str(v / "talk.mp4")})
        d = self.json("/api/project")
        project = d["project"]
        status = self.json("/api/shorts")
        self.assertTrue(status["claude"] and status["whisper"] and status["models"], status)

        def run(**options):
            self.json("/api/shorts", {"project": project, **options})
            deadline = time.time() + 90
            while (state := self.json("/api/export"))["state"] == "running":
                self.assertLess(time.time(), deadline)
                time.sleep(0.3)
            self.assertEqual(state["state"], "done", state["error"])
            return state["result"]

        result = run(count=3, length="short", claude=True)
        heard = json.loads(self.fake_claude_log.read_text())
        self.assertEqual(heard["args"][:3], ["-p", "--tools", ""], "Claude Code runs with its tools off")
        self.assertIn("--json-schema", heard["args"])
        self.assertIn("[0.0-1.5] How does this work?", heard["prompt"], "it gets the transcript, line by line")
        self.assertEqual(result["how"], "Claude Code")
        self.assertEqual([s["title"] for s in result["shorts"]], ["The one trick"], "made-up and overlapping picks dropped")
        short = result["shorts"][0]
        self.assertEqual(short["from"], 2.0)
        self.assertAlmostEqual(short["to"], 24.475, delta=0.01, msg="snapped to the end of sentence 11")
        made = json.loads((Path(self.tmp.name) / "data/cutline/projects" / short["file"]).read_text())
        self.assertEqual((made["canvas"]["w"], made["canvas"]["h"]), (720, 1280), "tall")
        pictures = [c for c in made["clips"] if c.get("kind") != "text"]
        self.assertEqual(len(pictures), short["cuts"], "one clip per spoken part")
        self.assertEqual(short["cuts"], 2, "the 1 s pause before 12 s is cut out")
        # 2.0-11.595 (to 0.12 s after the last word) and 12.9-24.475 (from 0.1 s before the next)
        self.assertAlmostEqual(short["length"], 9.595 + 11.575, delta=0.05)
        crop = pictures[0]["crop"]
        self.assertAlmostEqual(1 - crop["l"] - crop["r"], (9 / 16) / (16 / 9), places=3)
        self.assertEqual(pictures[0]["fit"], "fill")
        captions = [c for c in made["clips"] if c.get("kind") == "text" and c["track"] == 3]
        title = [c for c in made["clips"] if c.get("kind") == "text" and c["track"] == 4]
        self.assertEqual(len(captions), 11 * 4, "one caption per word")
        self.assertEqual(title[0]["text"], "The one trick")
        starts = sorted(c["start"] for c in captions)
        self.assertTrue(all(b > a for a, b in zip(starts, starts[1:], strict=False)))
        # the Short exports like any project
        self.json("/api/openproject", {"file": short["file"]})
        state = self.export(self.json("/api/project")["project"])
        self.assertEqual(state["state"], "done", state["error"])
        info = probe(state["output"])
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertAlmostEqual(int(video["nb_read_frames"]) / FPS, short["length"], delta=0.1)

        # without Claude Code: the built-in pick, starting at the question
        self.json("/api/new", {"path": str(v / "talk.mp4")})
        result = run(count=1, length="short", claude=False)
        self.assertEqual(result["how"], "built-in")
        self.assertEqual(result["shorts"][0]["from"], 0.0, "the question makes the best hook")

if __name__ == "__main__":
    unittest.main(verbosity=2)
