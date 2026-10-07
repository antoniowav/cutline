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
        env = {**os.environ, "XDG_DATA_HOME": str(tmp / "data"), "XDG_CACHE_HOME": str(tmp / "cache"),
               "CUTLINE_VIDEOS": str(cls.videos), "CUTLINE_NO_BROWSER": "1", "PYTHONDONTWRITEBYTECODE": "1",
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
