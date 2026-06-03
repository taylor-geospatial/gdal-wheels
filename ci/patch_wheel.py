#!/usr/bin/env python3
"""Post-repair wheel patcher for gdal-wheels.

After auditwheel/delocate/delvewheel have vendored libgdal + its C dependencies
into a wheel, this script makes the wheel fully self-contained at runtime by:

  1. injecting the GDAL data dir  -> osgeo/gdal_data/
  2. injecting the PROJ data dir  -> osgeo/proj_data/
  3. prepending ci/runtime_shim.py to osgeo/__init__.py so GDAL_DATA / PROJ_DATA
     are set (and the vendored DLL dir is registered on Windows) at import time.
  4. recomputing the dist-info RECORD and repackaging the wheel.

Usage:
  python ci/patch_wheel.py <input-wheel-or-glob> <dest-dir> \
      --gdal-data /path/to/share/gdal --proj-data /path/to/share/proj
"""

import argparse
import base64
import csv
import glob
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHIM = (HERE / "runtime_shim.py").read_text(encoding="utf-8")


def _record_hash(data):
    digest = hashlib.sha256(data).digest()
    b64 = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"sha256={b64}"


def patch(wheel_path, dest_dir, gdal_data, proj_data, licenses_src=None):
    wheel_path = Path(wheel_path)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with zipfile.ZipFile(wheel_path) as zf:
            zf.extractall(root)

        osgeo = root / "osgeo"
        if not osgeo.is_dir():
            sys.exit(f"ERROR: no osgeo/ package found in {wheel_path.name}")

        # 1 + 2: copy data trees in.
        for src, name in ((gdal_data, "gdal_data"), (proj_data, "proj_data")):
            if not src or not os.path.isdir(src):
                sys.exit(f"ERROR: data dir not found: {src}")
            dst = osgeo / name
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
            print(f"  injected {name} from {src}")

        # 2b: harvest bundled-dependency license files (vcpkg writes one
        # <prefix>/share/<port>/copyright per dep) into osgeo/licenses/, so the
        # wheel ships the licenses of every vendored library (BSD/MIT/LGPL/...).
        if licenses_src:
            licdir = osgeo / "licenses"
            licdir.mkdir(exist_ok=True)
            count = 0
            for cp in glob.glob(os.path.join(licenses_src, "share", "*", "copyright")):
                port = os.path.basename(os.path.dirname(cp))
                shutil.copy(cp, licdir / f"{port}.txt")
                count += 1
            print(f"  harvested {count} dependency license files into osgeo/licenses/")

        # 3: prepend the runtime shim to osgeo/__init__.py.
        init = osgeo / "__init__.py"
        original = init.read_text(encoding="utf-8") if init.exists() else ""
        if "gdal-wheels runtime shim" not in original:
            init.write_text(SHIM + "\n\n" + original, encoding="utf-8")
            print("  prepended runtime shim to osgeo/__init__.py")

        # 4: rebuild RECORD, then re-zip.
        dist_info = next(root.glob("*.dist-info"))
        record_path = dist_info / "RECORD"
        rows = []
        for path in sorted(root.rglob("*")):
            if path.is_dir() or path == record_path:
                continue
            rel = path.relative_to(root).as_posix()
            data = path.read_bytes()
            rows.append((rel, _record_hash(data), str(len(data))))
        rows.append((record_path.relative_to(root).as_posix(), "", ""))
        with open(record_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)

        out = dest_dir / wheel_path.name
        if out.exists():
            out.unlink()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(root).as_posix())
        print(f"  wrote {out}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wheel", help="input wheel path or glob")
    ap.add_argument("dest_dir", help="output directory")
    ap.add_argument("--gdal-data", required=True)
    ap.add_argument("--proj-data", required=True)
    ap.add_argument("--licenses-src", default=None,
                    help="prefix containing share/<port>/copyright files to bundle")
    args = ap.parse_args()

    matches = glob.glob(args.wheel)
    if not matches:
        sys.exit(f"ERROR: no wheel matched {args.wheel}")
    for w in matches:
        print(f"Patching {os.path.basename(w)} ...")
        patch(w, args.dest_dir, args.gdal_data, args.proj_data, args.licenses_src)


if __name__ == "__main__":
    main()
