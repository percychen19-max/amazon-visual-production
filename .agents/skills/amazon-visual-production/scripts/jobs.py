"""Register and check Amazon visual work, with one job.json per SKU."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

from PIL import Image, ImageChops, ImageOps, ImageStat


FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "TIFF": ".tif"}
SHOT_ID = re.compile(r"[\w-]+", re.UNICODE)


def positive(value):
    number = int(value)
    if number < 1:
        raise ValueError("版本号必须为正整数")
    return number


def contained(root, path):
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"路径超出 SKU 工作目录：{path}")
    return resolved


def load_job(path):
    root = path.parent.resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not isinstance(data.get("sku"), str) or not data["sku"].strip():
        raise ValueError("job.json 需要 schema=1 和非空 sku")
    shots = {}
    for shot in data["shots"]:
        key = shot["id"]
        if not isinstance(key, str) or not SHOT_ID.fullmatch(key) or key in shots:
            raise ValueError(f"图号无效或重复：{key}")
        if not isinstance(shot["variant"], str) or not shot["variant"].strip():
            raise ValueError(f"{key} 缺少变体；单款可填 default")
        card = Path(shot["card"])
        if card.is_absolute():
            raise ValueError(f"{key} 需要 SKU 目录内制作卡的相对路径：{card}")
        contained(root, card)
        spec = shot["spec"]
        if spec["format"] not in FORMATS:
            raise ValueError(f"{key} 的交付格式需为 {', '.join(FORMATS)}")
        if any(type(spec[k]) is not int or spec[k] < 1 for k in ("width", "height")):
            raise ValueError(f"{key} 需要有效的目标像素")
        shots[key] = shot
    if not shots:
        raise ValueError("至少需要一个图号")
    return root, data["sku"], shots


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inspect_image(path):
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        image.load()
        fmt = image.format
        width, height = ImageOps.exif_transpose(image).size
    if fmt not in FORMATS:
        raise ValueError(f"不支持的图像格式：{fmt}")
    return {"format": fmt, "width": width, "height": height, "sha256": digest(path)}


def validate_spec(info, spec):
    for key in ("format", "width", "height"):
        if info[key] != spec[key]:
            raise ValueError(f"{key} 应为 {spec[key]}，文件实际为 {info[key]}")


def version_dir(root, shot, version):
    return contained(root, Path("versions") / shot["id"] / f"v{version:03d}")


def version_numbers(root, shot):
    folder = contained(root, Path("versions") / shot["id"])
    return sorted(int(p.name[1:]) for p in folder.glob("v*")
                  if p.is_dir() and re.fullmatch(r"v[0-9]+", p.name))


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@contextmanager
def writing(root):
    # The lock has a stable inode even when version directories are published by rename.
    with contained(root, ".jobs.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def check_version_files(root, sku, shot, version, spec=None):
    folder = version_dir(root, shot, version)
    record = json.loads((folder / "record.json").read_text(encoding="utf-8"))
    if (record["sku"], record["shot"], record["variant"], record["version"]) != (
            sku, shot["id"], shot["variant"], version):
        raise ValueError("版本记录与当前 SKU、变体、图号或版本不一致")
    if digest(folder / "card.md") != record["card_sha256"]:
        raise ValueError("归档制作卡校验失败")
    decoded = {}
    for item in ("delivery", "raw"):
        stored = record[item]
        image_path = contained(folder, stored["file"])
        if image_path not in decoded:
            decoded[image_path] = inspect_image(image_path)
        actual = decoded[image_path]
        if actual["sha256"] != stored["sha256"]:
            raise ValueError(f"{image_path.name} 的内容已改变")
        validate_spec(actual, stored)
        if item == "delivery":
            validate_spec(actual, record["spec"])
            if spec is not None:
                validate_spec(actual, spec)
    return record


def audited_lineage(root, sku, shot, version, spec=None):
    """Verify the requested version and each ancestor, returning newest first."""
    current = check_version_files(root, sku, shot, version, spec)
    records = [current]
    while current["parent"] is not None:
        parent = current["parent"]
        if type(parent) is not int or not 0 < parent < current["version"]:
            raise ValueError("底图版本号必须为早于当前版本的正整数")
        try:
            current = check_version_files(root, sku, shot, parent)
        except (OSError, ValueError, KeyError, TypeError, SyntaxError) as exc:
            raise ValueError(f"底图 v{parent:03d} 校验失败：{exc}") from exc
        records.append(current)
    return records


def stage_image(source, folder, name):
    temporary = folder / name
    shutil.copyfile(source, temporary)
    info = inspect_image(temporary)
    final = temporary.with_suffix(FORMATS[info["format"]])
    temporary.rename(final)
    return {**info, "file": final.name}


def register(root, sku, shot, args):
    target = version_dir(root, shot, args.version)
    if args.parent is not None:
        if args.parent >= args.version:
            raise ValueError("底图版本必须先于新版本")
        audited_lineage(root, sku, shot, args.parent)
    existing = version_numbers(root, shot)
    if existing:
        prior = version_dir(root, shot, max(existing)) / "record.json"
        identity = json.loads(prior.read_text(encoding="utf-8"))
        if (identity["sku"], identity["variant"], identity["shot"]) != (sku, shot["variant"], shot["id"]):
            raise ValueError("该图号已有其他 SKU 或变体的版本，请使用独立图号")
    if existing and not target.exists() and args.version <= max(existing):
        raise ValueError("新版本号必须大于已登记的版本")
    target.parent.mkdir(parents=True, exist_ok=True)
    # An incomplete staging directory never appears as a registered version.
    with tempfile.TemporaryDirectory(prefix=".stage-", dir=target.parent) as temp:
        staged = Path(temp) / "complete"
        staged.mkdir()
        delivery = stage_image(args.file, staged, "image")
        validate_spec(delivery, shot["spec"])
        raw = stage_image(args.raw, staged, "original") if args.raw else delivery
        card = contained(root, shot["card"])
        shutil.copyfile(card, staged / "card.md")
        record = {
            "sku": sku, "shot": shot["id"], "variant": shot["variant"],
            "version": args.version, "parent": args.parent, "spec": shot["spec"],
            "card": shot["card"], "card_sha256": digest(staged / "card.md"),
            "delivery": delivery, "raw": raw,
        }
        if target.exists():
            if audited_lineage(root, sku, shot, args.version)[0] != record:
                raise ValueError("此版本已登记其他内容或制作卡；请保留旧版并使用新版本号")
        else:
            write_json(staged / "record.json", record)
            staged.rename(target)
    return {"record": str((target / "record.json").relative_to(root)),
            "status": "待视觉核对", "delivery": delivery, "raw": raw}


def failures(root, shot):
    path = contained(root, Path("versions") / shot["id"] / "failures.json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def mark_failure(root, shot, args):
    latest = max(version_numbers(root, shot), default=0)
    version = args.version if args.version else latest + 1
    if version <= latest or not args.reason.strip():
        raise ValueError("失败记录需要高于已登记版本的版本号以及具体原因")
    folder = version_dir(root, shot, version).parent
    folder.mkdir(parents=True, exist_ok=True)
    events = failures(root, shot)
    entry = {"version": version, "reason": args.reason}
    if entry not in events:
        events.append(entry)
        with tempfile.TemporaryDirectory(dir=folder, prefix=".failure-") as temp:
            path = Path(temp) / "failures.json"
            write_json(path, events)
            os.replace(path, folder / path.name)
    return entry


def report(root, sku, shot, version=None):
    versions = version_numbers(root, shot)
    latest = max(versions, default=0)
    target = version if version is not None else latest or None
    pending = [e for e in failures(root, shot) if e["version"] > latest]
    info = {"shot": shot["id"], "variant": shot["variant"], "versions": versions,
            "checked_version": target, "outstanding_failures": pending,
            "status": "待重试" if pending else "待生成", "technical_pass": False}
    if version is None and not contained(root, shot["card"]).is_file():
        info.update(status="缺少制作卡", error=f"找不到制作卡：{shot['card']}")
        return info
    if target is None or target not in versions:
        info["error"] = "缺少已登记文件"
        return info
    try:
        saved = audited_lineage(root, sku, shot, target, shot["spec"] if version is None else None)[0]
        info.update(technical_pass=True, parent=saved["parent"], delivery=saved["delivery"],
                    raw=saved["raw"], status="待重试" if pending else "已登记，待视觉核对")
    except (OSError, ValueError, KeyError, TypeError, SyntaxError) as exc:
        info.update(status="文件异常", error=str(exc))
    return info


def native_rgb(root, shot, record):
    path = contained(version_dir(root, shot, record["version"]), record["raw"]["file"])
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def drift(root, sku, shot, version, box):
    lineage = audited_lineage(root, sku, shot, version)
    if len(lineage) < 2:
        raise ValueError(f"v{version:03d} 没有底图版本，无法比较")
    revised = native_rgb(root, shot, lineage[0])
    parent = native_rgb(root, shot, lineage[1])
    if parent.size != revised.size:
        raise ValueError(f"原生图尺寸不同：底图 {parent.size}，修订图 {revised.size}")
    width, height = parent.size
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError(f"编辑框需满足 0 ≤ x1 < x2 ≤ {width}，0 ≤ y1 < y2 ≤ {height}")
    protected = width * height - (x2 - x1) * (y2 - y1)
    if protected == 0:
        raise ValueError("编辑框覆盖了整图，没有可比较的保护区域")

    mask = Image.new("L", parent.size, 255)
    mask.paste(0, tuple(box))
    delta = ImageChops.difference(revised, parent)
    means = ImageStat.Stat(delta, mask).mean
    red, green, blue = delta.split()
    largest_difference = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    identical = largest_difference.histogram(mask=mask)[0]
    return {
        "sku": sku, "shot": shot["id"], "variant": shot["variant"],
        "version": version, "parent": lineage[1]["version"], "native_size": [width, height],
        "edit_box": box, "protected_pixels": protected,
        "mean_absolute_difference_rgb": dict(zip(("R", "G", "B"), means)),
        "identical_rgb_fraction": identical / protected,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    for cmd in ("status", "check"):
        p = commands.add_parser(cmd)
        p.add_argument("shot", nargs="?")
        p.add_argument("--version", type=positive)
    p = commands.add_parser("drift", help="比较父子版本的原生图在允许编辑框之外的 RGB 差异")
    p.add_argument("shot")
    p.add_argument("--version", type=positive, required=True)
    p.add_argument("--edit-box", nargs=4, type=int, required=True, metavar=("X1", "Y1", "X2", "Y2"),
                   help="按 EXIF 转正后的原生像素坐标，含左上边界，不含右下边界")
    p = commands.add_parser("register")
    p.add_argument("shot")
    p.add_argument("--version", type=positive, required=True)
    p.add_argument("--parent", type=positive)
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--raw", type=Path)
    p = commands.add_parser("fail")
    p.add_argument("shot")
    p.add_argument("--version", type=positive)
    p.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        root, sku, shots = load_job(args.manifest)
        if args.shot is not None and args.shot not in shots:
            raise ValueError(f"图号不存在：{args.shot}")
        if args.command in ("check", "status"):
            if args.version is not None and args.shot is None:
                raise ValueError("指定版本时请同时指定图号")
            chosen = [shots[args.shot]] if args.shot is not None else shots.values()
            rows = [report(root, sku, shot, args.version) for shot in chosen]
            result = {"sku": sku, "shots": rows}
            code = int(args.command == "check" and any(not r["technical_pass"] or
                       (args.version is None and r["outstanding_failures"]) for r in rows))
        elif args.command == "drift":
            result = drift(root, sku, shots[args.shot], args.version, args.edit_box)
            code = 0
        else:
            with writing(root):
                if args.command == "register":
                    result = register(root, sku, shots[args.shot], args)
                else:
                    result = mark_failure(root, shots[args.shot], args)
            code = 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (OSError, ValueError, KeyError, TypeError, SyntaxError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
