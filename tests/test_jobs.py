"""Run with python3 -m unittest discover -s tests -p 'test_jobs.py'."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image


PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT / ".agents/skills/amazon-visual-production/scripts/jobs.py"


class JobWorkflowTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.card = self.root / "card.md"
        self.card.write_text("SKU A — original front view", encoding="utf-8")
        self.manifest = self.root / "job.json"
        self.shot = {"id": "MAIN-blue", "variant": "蓝", "card": "card.md",
                     "spec": {"width": 64, "height": 48, "format": "PNG"}}
        self.write_job()
        self.image = self.root / "source.png"
        Image.new("RGB", (64, 48), (20, 160, 200)).save(self.image)
        self.raw = self.root / "original.jpg"
        Image.new("RGB", (32, 24), (20, 160, 200)).save(self.raw)
        self.first = ("register", "MAIN-blue", "--version", "1", "--file", self.image)

    def write_job(self, shots=None):
        self.manifest.write_text(json.dumps({"schema": 1, "sku": "A", "shots":
                                            [self.shot] if shots is None else shots}), encoding="utf-8")

    def cli(self, *args, expect=0):
        result = subprocess.run([sys.executable, SCRIPT, "--manifest", self.manifest, *args],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return json.loads(result.stdout) if result.stdout else result.stderr

    def test_recovery_and_lineage(self):
        self.assertFalse(self.cli("check", expect=1)["shots"][0]["technical_pass"])
        self.cli("fail", "MAIN-blue", "--reason", "无图片结果")
        self.cli(*self.first, "--raw", self.raw)
        first = self.cli("check")["shots"][0]
        self.assertEqual(first["outstanding_failures"], [])
        self.assertEqual((first["raw"]["width"], first["delivery"]["width"]), (32, 64))
        saved = self.root / "versions/MAIN-blue/v001"
        self.assertEqual((saved / "original.jpg").read_bytes(), self.raw.read_bytes())
        self.assertEqual((saved / "image.png").read_bytes(), self.image.read_bytes())
        old_card = self.card.read_bytes()
        self.card.write_text("Keep product. Revise the background.", encoding="utf-8")
        self.cli("fail", "MAIN-blue", "--version", "2", "--reason", "请求中断")
        self.assertEqual(self.cli("check", expect=1)["shots"][0]["checked_version"], 1)
        self.cli("register", "MAIN-blue", "--version", "2", "--parent", "1", "--file", self.image)
        self.assertEqual(self.cli("check")["shots"][0]["parent"], 1)
        self.assertEqual((saved / "card.md").read_bytes(), old_card)
        self.assertTrue(self.cli("check", "MAIN-blue", "--version", "1")["shots"][0]["technical_pass"])

    def test_atomic_and_idempotent_concurrent_registration(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.cli(*self.first), range(4)))
        self.assertEqual(len({r["record"] for r in results}), 1)
        alternate = self.root / "different.png"
        Image.new("RGB", (64, 48), "white").save(alternate)
        self.cli("register", "MAIN-blue", "--version", "1", "--file", alternate, expect=2)
        first = self.root / "versions/MAIN-blue/v001/image.png"
        self.assertEqual(first.read_bytes(), self.image.read_bytes())
        self.assertEqual(self.cli("status")["shots"][0]["versions"], [1])

    def test_invalid_file_sizes_formats_and_missing_assets(self):
        self.cli("register", "MAIN-blue", "--version", "1", "--file", self.raw, expect=2)
        fake_png = self.root / "disguised.png"
        Image.new("RGB", (64, 48)).save(fake_png, format="JPEG")
        self.assertIn("format", self.cli("register", "MAIN-blue", "--version", "1",
                                          "--file", fake_png, expect=2))
        Image.new("RGB", (63, 48)).save(fake_png)
        self.assertIn("width", self.cli("register", "MAIN-blue", "--version", "1",
                                        "--file", fake_png, expect=2))
        fake_png.write_bytes(b"no image")
        self.cli("register", "MAIN-blue", "--version", "1", "--file", fake_png, expect=2)
        self.assertEqual(self.cli("status")["shots"][0]["versions"], [])
        self.cli(*self.first)
        (self.root / "versions/MAIN-blue/v001/image.png").unlink()
        checked = self.cli("check", expect=1)["shots"][0]
        self.assertFalse(checked["technical_pass"])

    def test_parent_and_changed_variant(self):
        self.cli("register", "MAIN-blue", "--version", "2", "--parent", "1", "--file",
                 self.image, expect=2)
        self.cli(*self.first)
        self.shot["variant"] = "另一个变体"
        self.write_job()
        self.cli("register", "MAIN-blue", "--version", "2", "--file", self.image, expect=2)
        self.assertFalse(self.cli("check", expect=1)["shots"][0]["technical_pass"])

    def test_changed_target_vs_immutable_history(self):
        self.cli(*self.first)
        self.shot["spec"]["width"] = 92
        self.write_job()
        self.assertIn("width", self.cli("check", expect=1)["shots"][0]["error"])
        self.assertTrue(self.cli("check", "MAIN-blue", "--version", "1")["shots"][0]["technical_pass"])

    def test_duplicate_id_and_escape(self):
        self.write_job([self.shot, self.shot])
        self.assertIn("重复", self.cli("status", expect=2))
        self.shot["id"] = "../other"
        self.write_job()
        self.cli("status", expect=2)
        self.shot["id"] = "MAIN"
        self.shot["card"] = "../card.md"
        self.write_job()
        self.assertIn("超出", self.cli("status", expect=2))

    def test_missing_card_only_blocks_affected_shot(self):
        other = {**self.shot, "id": "L02", "card": "missing.md"}
        self.write_job([self.shot, other])
        self.cli(*self.first)
        rows = self.cli("check", expect=1)["shots"]
        self.assertTrue(rows[0]["technical_pass"])
        self.assertEqual(rows[1]["status"], "缺少制作卡")
        self.assertTrue(self.cli("check", "MAIN-blue")["shots"][0]["technical_pass"])

    def test_higher_success_supersedes_only_earlier_failed_versions(self):
        self.cli(*self.first)
        self.cli("fail", "MAIN-blue", "--version", "2", "--reason", "初次返工中断")
        self.cli("fail", "MAIN-blue", "--version", "4", "--reason", "另一次返工中断")
        self.cli("register", "MAIN-blue", "--version", "3", "--parent", "1", "--file", self.image)
        pending = self.cli("check", expect=1)["shots"][0]["outstanding_failures"]
        self.assertEqual([e["version"] for e in pending], [4])
        self.cli("fail", "MAIN-blue", "--version", "2", "--reason", "已被 v3 取代", expect=2)
        self.cli("register", "MAIN-blue", "--version", "5", "--parent", "3", "--file", self.image)
        self.assertEqual(self.cli("check")["shots"][0]["outstanding_failures"], [])
        history = json.loads((self.root / "versions/MAIN-blue/failures.json").read_text())
        self.assertEqual([e["version"] for e in history], [2, 4])

    def test_check_verifies_full_parent_lineage(self):
        self.cli(*self.first)
        self.cli("register", "MAIN-blue", "--version", "2", "--parent", "1", "--file", self.image)
        self.cli("register", "MAIN-blue", "--version", "3", "--parent", "2", "--file", self.image)
        (self.root / "versions/MAIN-blue/v001/image.png").unlink()
        check = self.cli("check", expect=1)["shots"][0]
        self.assertEqual(check["checked_version"], 3)
        self.assertFalse(check["technical_pass"])
        self.assertIn("底图 v001", check["error"])

    def test_drift_compares_oriented_native_rgb_outside_edit_box_read_only(self):
        parent = Image.new("RGB", (3, 2), (10, 20, 30))
        parent.putpixel((2, 1), (180, 100, 250))
        edited = parent.copy()
        edited.putpixel((0, 0), (255, 255, 255))  # This pixel is inside the edit box.
        edited.putpixel((1, 0), (15, 10, 50))
        edited.putpixel((2, 1), (160, 115, 220))
        rotated_parent = self.root / "rotated.png"
        edit_path = self.root / "edit.png"
        exif = Image.Exif()
        exif[274] = 6
        parent.transpose(Image.Transpose.ROTATE_90).save(rotated_parent, exif=exif)
        edited.save(edit_path)
        self.cli(*self.first, "--raw", rotated_parent)
        self.cli("register", "MAIN-blue", "--version", "2", "--parent", "1",
                 "--file", self.image, "--raw", edit_path)
        before = {p: p.stat().st_mtime_ns for p in self.root.rglob("*")}
        result = self.cli("drift", "MAIN-blue", "--version", "2", "--edit-box", "0", "0", "1", "1")
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in self.root.rglob("*")})
        self.assertEqual((result["parent"], result["native_size"], result["protected_pixels"]),
                         (1, [3, 2], 5))
        self.assertEqual(result["mean_absolute_difference_rgb"], {"R": 5, "G": 5, "B": 10})
        self.assertEqual(result["identical_rgb_fraction"], 3 / 5)

    def test_drift_rejects_invalid_boxes_and_missing_parent(self):
        self.cli(*self.first)
        drift = ("drift", "MAIN-blue", "--version")
        self.assertIn("没有底图", self.cli(*drift, "1", "--edit-box", "0", "0", "1", "1", expect=2))
        self.cli("register", "MAIN-blue", "--version", "2", "--parent", "1", "--file", self.image)
        for box in ((0, 0, 0, 1), (-1, 0, 1, 1), (0, 0, 65, 48), (1, 2, 5, 1)):
            with self.subTest(box=box):
                self.assertIn("编辑框", self.cli(*drift, "2", "--edit-box", *map(str, box), expect=2))
        self.assertIn("保护区域", self.cli(*drift, "2", "--edit-box", "0", "0", "64", "48", expect=2))
        check = self.cli(*drift, "2", "--edit-box", "62", "47", "64", "48")
        self.assertEqual(check["identical_rgb_fraction"], 1)
        self.assertEqual(check["protected_pixels"], 64 * 48 - 2)
        (self.root / "versions/MAIN-blue/v001/image.png").unlink()
        self.assertIn("底图 v001", self.cli(*drift, "2", "--edit-box", "0", "0", "1", "1", expect=2))

    def test_drift_rejects_different_native_sizes(self):
        self.cli(*self.first)
        self.cli("register", "MAIN-blue", "--version", "2", "--parent", "1",
                 "--file", self.image, "--raw", self.raw)
        error = self.cli("drift", "MAIN-blue", "--version", "2", "--edit-box",
                         "0", "0", "1", "1", expect=2)
        self.assertIn("原生图尺寸不同", error)


if __name__ == "__main__":
    unittest.main()
