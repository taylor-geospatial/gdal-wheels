#!/usr/bin/env python3
"""Install the freshly built base + tools wheels into an isolated venv and
verify the GDAL C command-line tools actually run, then emit a size report.

Run in CI after the wheels are built. Fails non-zero if a tool is missing or a
real conversion fails, so a broken tools wheel never ships.

Usage:
  python ci/verify_tools_wheel.py <base-wheelhouse> <tools-wheelhouse> \
      [--report <markdown-out>]
"""

import argparse
import glob
import os
import subprocess
import sys
import sysconfig
import tempfile
import venv
from pathlib import Path


def _newest(pattern):
    matches = sorted(glob.glob(pattern), key=os.path.getmtime)
    return matches[-1] if matches else None


def _pick_base_wheel(wheelhouse):
    """Pick a base (osgeo) wheel installable by the CURRENT interpreter.

    cibuildwheel emits one base wheel per Python (cp312/cp313/cp313t/cp314/
    cp314t). The verify step runs under a single interpreter (3.12), so a plain
    "newest" pick lands on the cp314t free-threaded wheel and pip rejects it
    ("not a supported wheel on this platform"). Match the running interpreter's
    cpXY[t] tag instead; fall back to newest only if nothing matches.
    """
    import sysconfig as _sc

    matches = glob.glob(os.path.join(wheelhouse, "*.whl"))
    if not matches:
        return None
    free_threaded = bool(_sc.get_config_var("Py_GIL_DISABLED"))
    tag = "cp{}{}{}".format(
        sys.version_info[0], sys.version_info[1], "t" if free_threaded else ""
    )
    # exact interpreter tag, e.g. "cp312-" (the trailing dash avoids matching
    # cp312t when we want cp312, and cp31* prefixes).
    want = f"{tag}-"
    compatible = [m for m in matches if want in os.path.basename(m)]
    if compatible:
        return sorted(compatible, key=os.path.getmtime)[-1]
    return _newest(os.path.join(wheelhouse, "*.whl"))


def _venv_bin(venv_dir):
    # scripts dir where .data/scripts/ launchers land
    return Path(venv_dir) / ("Scripts" if os.name == "nt" else "bin")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base_wheelhouse")
    ap.add_argument("tools_wheelhouse")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    base = _pick_base_wheel(args.base_wheelhouse)
    tools = _newest(os.path.join(args.tools_wheelhouse, "*.whl"))
    if not base:
        sys.exit(f"ERROR: no base wheel in {args.base_wheelhouse}")
    if not tools:
        sys.exit(f"ERROR: no tools wheel in {args.tools_wheelhouse}")

    base_mb = os.path.getsize(base) / 1e6
    tools_mb = os.path.getsize(tools) / 1e6
    print(f"base  wheel: {os.path.basename(base)}  {base_mb:.1f} MB")
    print(f"tools wheel: {os.path.basename(tools)}  {tools_mb:.1f} MB")
    print(f"total: {base_mb + tools_mb:.1f} MB  (tools add {tools_mb:.1f} MB)")

    with tempfile.TemporaryDirectory() as td:
        vdir = os.path.join(td, "venv")
        venv.create(vdir, with_pip=True)
        bindir = _venv_bin(vdir)
        py = bindir / ("python.exe" if os.name == "nt" else "python")

        # install base first (osgeo), then tools (osgeo_tools + launchers).
        subprocess.run([str(py), "-m", "pip", "install", "-q",
                        base, tools], check=True)

        # The launchers were installed into the venv's scripts dir + are on PATH
        # when the venv is activated. We invoke them by absolute path here.
        env = dict(os.environ)
        env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")

        def tool(name):
            exe = bindir / (f"{name}.bat" if os.name == "nt" else name)
            if not exe.exists() and os.name == "nt":
                exe = bindir / name  # pip may strip .bat semantics
            return str(exe)

        # 1. gdalinfo --version
        for t in ("gdalinfo", "ogr2ogr", "ogrinfo", "gdalwarp"):
            r = subprocess.run([tool(t), "--version"], env=env,
                               capture_output=True, text=True)
            print(f"$ {t} --version\n{r.stdout.strip() or r.stderr.strip()}")
            if r.returncode != 0:
                sys.exit(f"ERROR: {t} --version failed (rc={r.returncode}):\n{r.stderr}")
            if "GDAL" not in (r.stdout + r.stderr):
                sys.exit(f"ERROR: {t} --version did not report GDAL")

        # 2. a real ogr2ogr conversion: GeoJSON -> GPKG, then ogrinfo it.
        src = os.path.join(td, "in.geojson")
        Path(src).write_text(
            '{"type":"FeatureCollection","features":[{"type":"Feature",'
            '"properties":{"name":"a","val":1},"geometry":{"type":"Point",'
            '"coordinates":[1.0,2.0]}}]}', encoding="utf-8")
        dst = os.path.join(td, "out.gpkg")
        r = subprocess.run([tool("ogr2ogr"), "-f", "GPKG", dst, src],
                           env=env, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"ERROR: ogr2ogr conversion failed:\n{r.stderr}")
        if not os.path.exists(dst):
            sys.exit("ERROR: ogr2ogr produced no output GPKG")
        r = subprocess.run([tool("ogrinfo"), "-al", "-so", dst],
                           env=env, capture_output=True, text=True)
        if r.returncode != 0 or "Feature Count: 1" not in r.stdout:
            sys.exit(f"ERROR: ogrinfo could not read converted GPKG:\n"
                     f"{r.stdout}\n{r.stderr}")
        print("$ ogr2ogr GeoJSON->GPKG + ogrinfo round-trip: OK (1 feature)")

        # 3. gdalinfo on a tiny GTiff produced via the python bindings (proves
        #    the CLI reads what the bindings wrote -> data dirs/PROJ resolved).
        from_py = os.path.join(td, "mk.py")
        Path(from_py).write_text(
            "from osgeo import gdal, osr\n"
            "import numpy as np\n"
            "gdal.UseExceptions()\n"
            f"ds=gdal.GetDriverByName('GTiff').Create(r'{os.path.join(td,'t.tif')}',4,4,1,gdal.GDT_Byte)\n"
            "ds.SetGeoTransform((0,1,0,0,0,-1))\n"
            "s=osr.SpatialReference(); s.ImportFromEPSG(4326); ds.SetProjection(s.ExportToWkt())\n"
            "ds.GetRasterBand(1).WriteArray(np.ones((4,4),'uint8'))\n"
            "ds=None\n", encoding="utf-8")
        subprocess.run([str(py), from_py], check=True, env=env)
        r = subprocess.run([tool("gdalinfo"), os.path.join(td, "t.tif")],
                           env=env, capture_output=True, text=True)
        if r.returncode != 0 or "Size is 4, 4" not in r.stdout:
            sys.exit(f"ERROR: gdalinfo failed on python-built GTiff:\n{r.stdout}\n{r.stderr}")
        print("$ gdalinfo on python-built GTiff: OK (Size is 4, 4, CRS resolved)")

    print("TOOLS VERIFICATION PASSED")

    if args.report:
        plat = sysconfig.get_platform()
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(f"| {plat} | {base_mb:.1f} | {tools_mb:.1f} | "
                    f"{base_mb + tools_mb:.1f} |\n")
        print(f"wrote size report row -> {args.report}")


if __name__ == "__main__":
    main()
