#!/usr/bin/env python3
"""Assemble the ``gdal-wheels-tools`` wheel: GDAL's compiled C command-line
tools (gdalinfo, ogr2ogr, ogrinfo, gdalwarp, gdal_translate, gdalbuildvrt,
gdaladdo, gdalsrsinfo, the unified ``gdal`` app, ...) shipped onto the user's
PATH.

The base ``gdal-wheels`` wheel deliberately ships only the Python ``osgeo``
bindings (lean). OSGeo/gdal#3060 users still want the C CLI tools, so we publish
them as a SEPARATE, OPT-IN distribution.

Design (why self-contained):
  * The tools wheel vendors its OWN copy of libgdal + the full C dependency
    stack next to the binaries, instead of trying to reuse the base wheel's
    libs. The base wheel's libs are SONAME-mangled and live in a hash-suffixed
    dir (``osgeo.libs`` / ``osgeo/.dylibs``) that no external binary can resolve
    portably. Self-containment means the tools work with OR without the base
    wheel installed, with no cross-wheel version coupling -- the same model
    system/conda packages use (apps sit beside their libs).
  * Binaries live inside the import package ``osgeo_tools/`` together with their
    libs + gdal_data/proj_data. RPATH (``$ORIGIN``/``@loader_path``) makes the
    binaries find the adjacent libs on Linux/macOS; on Windows the DLLs sit in
    the same directory as the .exe (the default search path).
  * Thin launcher scripts are placed in the wheel's ``*.data/scripts/`` dir,
    which pip installs onto PATH (``<env>/bin`` or ``Scripts``). Each launcher
    sets GDAL_DATA/PROJ_DATA to the bundled data and exec's the real binary, so
    the tools are self-contained regardless of the user's environment.

This produces a pure-binary wheel tagged ``py3-none-<platform>`` (no Python
extension, no per-Python build) -- one tools wheel per platform.

Usage:
  python ci/build_tools_wheel.py <install-prefix> <dest-dir> \
      --version <gdal-version> --platform-tag <wheel-platform-tag> \
      [--licenses-src <prefix>]
"""

import argparse
import base64
import csv
import hashlib
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

PKG = "osgeo_tools"

# GDAL's C command-line apps. We ship the ones GDAL's CMake installs into bin/
# when BUILD_APPS=ON. We discover the actual set on disk (so we never ship a
# stale list), but keep this as the documented/expected core for sanity-check.
CORE_APPS = [
    "gdal",  # GDAL 3.11+ unified entry point
    "gdalinfo", "gdal_translate", "gdaladdo", "gdalwarp", "gdalbuildvrt",
    "gdaldem", "gdal_grid", "gdal_rasterize", "gdal_contour", "gdaltindex",
    "gdallocationinfo", "gdaltransform", "gdalsrsinfo", "gdalmdiminfo",
    "gdalmdimtranslate", "nearblack", "gdalmanage", "gdal_viewshed",
    "gdal_footprint", "gdalenhance",
    "ogrinfo", "ogr2ogr", "ogrlineref", "ogrtindex", "sozip",
]


def _record_hash(data):
    digest = hashlib.sha256(data).digest()
    b64 = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"sha256={b64}"


def _is_macho_or_elf(path):
    """True if path is a native executable binary (not a shell/python script)."""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
    except OSError:
        return False
    # ELF, Mach-O (32/64, both endians), Windows PE handled separately by .exe
    return magic[:4] == b"\x7fELF" or magic[:4] in (
        b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",
        b"\xca\xfe\xba\xbe",  # fat/universal
    )


def discover_apps(bin_dir, is_windows):
    """Return the list of GDAL app binaries actually present in bin/."""
    found = []
    for entry in sorted(os.listdir(bin_dir)):
        p = bin_dir / entry
        if is_windows:
            if entry.lower().endswith(".exe") and not entry.lower().startswith(
                ("python", "vcpkg")
            ):
                found.append(entry)
        else:
            # skip the gdal-config helper script and anything non-binary
            if entry == "gdal-config":
                continue
            if p.is_file() and _is_macho_or_elf(p):
                found.append(entry)
    return found


# ---------------------------------------------------------------------------
# Library collection + RPATH fixups (Linux / macOS)
# ---------------------------------------------------------------------------

def _run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def _linux_needed_libs(binary):
    """Resolve the transitive shared-library closure of a binary via ldd."""
    out = subprocess.run(["ldd", str(binary)], capture_output=True, text=True)
    libs = set()
    for line in out.stdout.splitlines():
        line = line.strip()
        if "=>" in line:
            rhs = line.split("=>", 1)[1].strip()
            path = rhs.split(" (")[0].strip()
            if path and path != "not found" and os.path.exists(path):
                libs.add(os.path.realpath(path))
    return libs


def _macos_needed_libs(binary, search_libdir):
    """Resolve dependent dylibs of a binary via otool, restricted to ones we
    actually ship (skip system /usr/lib + /System frameworks)."""
    out = subprocess.run(["otool", "-L", str(binary)], capture_output=True, text=True)
    libs = set()
    for line in out.stdout.splitlines()[1:]:
        ref = line.strip().split(" (")[0].strip()
        if not ref:
            continue
        name = os.path.basename(ref)
        if ref.startswith("/usr/lib/") or ref.startswith("/System/"):
            continue
        cand = search_libdir / name
        if cand.exists():
            libs.add(os.path.realpath(cand))
    return libs


# System libraries that must NOT be vendored (they belong to the OS/loader and
# vendoring them causes crashes). Mirrors auditwheel/delocate policy.
_LINUX_SKIP_PREFIXES = (
    "ld-linux", "libc.so", "libc-", "libm.so", "libm-", "libdl.so", "libdl-",
    "libpthread", "librt.so", "librt-", "librt.", "libutil", "libnsl",
    "libresolv", "libgcc_s", "libstdc++", "libgomp", "libcrypt.so",
    "linux-vdso", "libcrypt-",
)


def _skip_linux(name):
    return any(name.startswith(p) for p in _LINUX_SKIP_PREFIXES)


def collect_unix(apps, bin_dir, lib_dir, payload_bin, payload_lib, is_macos):
    """Copy app binaries + their shared-library closure into the payload, then
    rewrite RPATHs so each binary/lib finds the bundled libs at runtime."""
    payload_bin.mkdir(parents=True, exist_ok=True)
    payload_lib.mkdir(parents=True, exist_ok=True)

    # 1. copy the app binaries.
    for app in apps:
        shutil.copy2(bin_dir / app, payload_bin / app)

    # 2. resolve + copy the full shared-lib closure (iterate to fixpoint).
    collected = {}
    frontier = list(payload_bin.iterdir())
    seen = set()
    while frontier:
        b = frontier.pop()
        rp = os.path.realpath(b)
        if rp in seen:
            continue
        seen.add(rp)
        needed = (_macos_needed_libs(b, lib_dir) if is_macos
                  else _linux_needed_libs(b))
        for libpath in needed:
            name = os.path.basename(libpath)
            if not is_macos and _skip_linux(name):
                continue
            if name not in collected:
                dst = payload_lib / name
                shutil.copy2(libpath, dst)
                os.chmod(dst, os.stat(dst).st_mode | stat.S_IWUSR)
                collected[name] = dst
                frontier.append(dst)
    print(f"  collected {len(collected)} shared libs into payload lib/")

    # 3. RPATH fixups so binaries (in bin/) find libs (in ../lib) and libs find
    #    each other (same dir).
    if is_macos:
        _fix_rpaths_macos(payload_bin, payload_lib)
    else:
        _fix_rpaths_linux(payload_bin, payload_lib)
    return collected


def _fix_rpaths_linux(payload_bin, payload_lib):
    for b in payload_bin.iterdir():
        _run(["patchelf", "--set-rpath", "$ORIGIN/../lib", str(b)])
    for lib in payload_lib.iterdir():
        if lib.is_file():
            _run(["patchelf", "--set-rpath", "$ORIGIN", str(lib)])


def _fix_rpaths_macos(payload_bin, payload_lib):
    # Rewrite each dependent install-name reference to @rpath/<libname> and add
    # an rpath pointing at the bundled lib dir.
    def fix(target, rpath_to_lib):
        out = subprocess.run(["otool", "-L", str(target)],
                             capture_output=True, text=True).stdout
        for line in out.splitlines()[1:]:
            ref = line.strip().split(" (")[0].strip()
            if not ref:
                continue
            if ref.startswith("/usr/lib/") or ref.startswith("/System/"):
                continue
            name = os.path.basename(ref)
            if (payload_lib / name).exists():
                subprocess.run(["install_name_tool", "-change", ref,
                                f"@rpath/{name}", str(target)],
                               capture_output=True)
        # set this binary's own id (libs only) and add the rpath
        subprocess.run(["install_name_tool", "-add_rpath", rpath_to_lib,
                        str(target)], capture_output=True)
        # ad-hoc re-sign (Apple silicon requires a valid signature after edits)
        subprocess.run(["codesign", "--force", "--sign", "-", str(target)],
                       capture_output=True)

    for b in payload_bin.iterdir():
        fix(b, "@loader_path/../lib")
    for lib in payload_lib.iterdir():
        if lib.is_file():
            # libs reference siblings in the same dir
            name = lib.name
            subprocess.run(["install_name_tool", "-id", f"@rpath/{name}",
                            str(lib)], capture_output=True)
            fix(lib, "@loader_path")


# ---------------------------------------------------------------------------
# Windows: copy .exe + all DLLs into one dir (DLLs sit next to the exe)
# ---------------------------------------------------------------------------

def collect_windows(apps, bin_dirs, payload_bin):
    payload_bin.mkdir(parents=True, exist_ok=True)
    for app in apps:
        for bd in bin_dirs:
            src = bd / app
            if src.exists():
                shutil.copy2(src, payload_bin / app)
                break
    # Copy every DLL from the provided bin dirs next to the exes. delvewheel-style
    # SONAME mangling is unnecessary here because the tools wheel is isolated;
    # the .exe finds DLLs in its own directory (Windows default search order).
    count = 0
    for bd in bin_dirs:
        if not bd.is_dir():
            continue
        for entry in os.listdir(bd):
            if entry.lower().endswith(".dll"):
                dst = payload_bin / entry
                if not dst.exists():
                    shutil.copy2(bd / entry, dst)
                    count += 1
    print(f"  collected {count} DLLs next to the .exe files")


# ---------------------------------------------------------------------------
# Launchers (placed in the wheel's *.data/scripts/ dir -> onto PATH)
# ---------------------------------------------------------------------------

UNIX_LAUNCHER = """\
#!/bin/sh
# gdal-wheels-tools launcher -- runs the bundled GDAL CLI tool with the wheel's
# vendored libgdal + GDAL/PROJ data, independent of any system GDAL.
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# scripts dir is <env>/bin; the package is <env>/lib/pythonX/site-packages
pkg=$(python3 -c "import os,osgeo_tools;print(os.path.dirname(osgeo_tools.__file__))" 2>/dev/null)
if [ -z "$pkg" ]; then
  pkg=$(python -c "import os,osgeo_tools;print(os.path.dirname(osgeo_tools.__file__))")
fi
export GDAL_DATA="${GDAL_DATA:-$pkg/gdal_data}"
export PROJ_DATA="${PROJ_DATA:-$pkg/proj_data}"
export PROJ_LIB="${PROJ_LIB:-$pkg/proj_data}"
exec "$pkg/bin/__APP__" "$@"
"""

# Windows: a .py console-script-style shim won't carry the .exe semantics well,
# so we ship a small launcher that resolves the package dir and exec's the exe.
WIN_LAUNCHER = """\
@echo off
setlocal
for /f "delims=" %%i in ('python -c "import os,osgeo_tools;print(os.path.dirname(osgeo_tools.__file__))"') do set PKG=%%i
if "%PKG%"=="" (echo gdal-wheels-tools: cannot locate osgeo_tools package & exit /b 1)
if "%GDAL_DATA%"=="" set GDAL_DATA=%PKG%\\gdal_data
if "%PROJ_DATA%"=="" set PROJ_DATA=%PKG%\\proj_data
if "%PROJ_LIB%"=="" set PROJ_LIB=%PKG%\\proj_data
"%PKG%\\bin\\__APP__" %*
"""


def write_launchers(apps, scripts_dir, is_windows):
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for app in apps:
        if is_windows:
            name = app[:-4] if app.lower().endswith(".exe") else app
            (scripts_dir / f"{name}.bat").write_text(
                WIN_LAUNCHER.replace("__APP__", app), encoding="utf-8")
        else:
            p = scripts_dir / app
            p.write_text(UNIX_LAUNCHER.replace("__APP__", app), encoding="utf-8")
            os.chmod(p, 0o755)


# ---------------------------------------------------------------------------
# Wheel packaging
# ---------------------------------------------------------------------------

def harvest_licenses(licenses_src, licdir):
    import glob
    licdir.mkdir(parents=True, exist_ok=True)
    count = 0
    for cp in glob.glob(os.path.join(licenses_src, "share", "*", "copyright")):
        port = os.path.basename(os.path.dirname(cp))
        shutil.copy(cp, licdir / f"{port}.txt")
        count += 1
    return count


def build_wheel(prefix, dest_dir, version, platform_tag, licenses_src):
    prefix = Path(prefix)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    is_windows = platform_tag.startswith("win")
    is_macos = platform_tag.startswith("macosx")

    bin_dir = prefix / "bin"
    # libs may be in lib/ or lib64/ depending on the platform install layout.
    lib_dir = prefix / "lib"
    if not lib_dir.is_dir() and (prefix / "lib64").is_dir():
        lib_dir = prefix / "lib64"

    apps = discover_apps(bin_dir, is_windows)
    if not apps:
        sys.exit(f"ERROR: no GDAL app binaries found in {bin_dir}")
    have = {a[:-4] if a.lower().endswith('.exe') else a for a in apps}
    missing_core = [a for a in CORE_APPS if a not in have]
    print(f"Discovered {len(apps)} app binaries; core apps missing: {missing_core or 'none'}")

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        pkg = root / PKG
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            '"""gdal-wheels-tools: bundled GDAL C command-line tools.\n\n'
            'Installs gdalinfo, ogr2ogr, gdalwarp, gdal_translate, etc. onto PATH.\n'
            'The compiled binaries + their libgdal/PROJ/GEOS/... stack and the\n'
            'GDAL/PROJ data live under this package; launcher scripts on PATH set\n'
            'GDAL_DATA/PROJ_DATA and exec them.\n"""\n'
            f'__version__ = "{version}"\n',
            encoding="utf-8")

        payload_bin = pkg / "bin"
        payload_lib = pkg / "lib"

        if is_windows:
            extra = []
            if licenses_src:
                extra = [Path(licenses_src) / "bin"]
            collect_windows(apps, [bin_dir] + extra, payload_bin)
        else:
            collect_unix(apps, bin_dir, lib_dir, payload_bin, payload_lib, is_macos)

        # bundle data dirs
        for name, sub in (("gdal_data", "share/gdal"), ("proj_data", "share/proj")):
            src = prefix / sub
            if not src.is_dir() and licenses_src:
                src = Path(licenses_src) / sub
            if src.is_dir():
                shutil.copytree(src, pkg / name)
                print(f"  bundled {name} from {src}")
            else:
                sys.exit(f"ERROR: data dir not found for {name}: {src}")

        if licenses_src:
            n = harvest_licenses(licenses_src, pkg / "licenses")
            print(f"  harvested {n} dependency license files")

        # dist-info
        dist = "gdal_wheels_tools"
        dist_info = root / f"{dist}-{version}.dist-info"
        dist_info.mkdir()
        (dist_info / "METADATA").write_text(
            "Metadata-Version: 2.1\n"
            f"Name: gdal-wheels-tools\n"
            f"Version: {version}\n"
            "Summary: GDAL command-line tools (gdalinfo, ogr2ogr, gdalwarp, ...) "
            "as a self-contained binary wheel, companion to gdal-wheels.\n"
            "License: MIT\n"
            "Requires-Python: >=3.8\n"
            "Project-URL: Homepage, https://github.com/taylor-geospatial/gdal-wheels\n"
            "\n"
            "Self-contained GDAL C command-line tools. Companion to ``gdal-wheels``.\n",
            encoding="utf-8")
        (dist_info / "WHEEL").write_text(
            "Wheel-Version: 1.0\n"
            "Generator: gdal-wheels build_tools_wheel.py\n"
            "Root-Is-Purelib: false\n"
            f"Tag: py3-none-{platform_tag}\n",
            encoding="utf-8")
        (dist_info / "top_level.txt").write_text(PKG + "\n", encoding="utf-8")

        # launcher scripts -> .data/scripts/
        data_scripts = root / f"{dist}-{version}.data" / "scripts"
        write_launchers(apps, data_scripts, is_windows)

        # RECORD
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

        # zip it (preserve unix exec bits)
        import zipfile
        wheel_name = f"{dist}-{version}-py3-none-{platform_tag}.whl"
        out = dest_dir / wheel_name
        if out.exists():
            out.unlink()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(root).as_posix()
                zi = zipfile.ZipInfo(rel)
                st = path.stat()
                # keep exec bit for binaries/launchers
                zi.external_attr = (st.st_mode & 0xFFFF) << 16
                zi.compress_type = zipfile.ZIP_DEFLATED
                with open(path, "rb") as fh:
                    zf.writestr(zi, fh.read())
        size_mb = out.stat().st_size / 1e6
        print(f"  wrote {out}  ({size_mb:.1f} MB, {len(apps)} tools)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix", help="install prefix containing bin/ lib/ share/")
    ap.add_argument("dest_dir")
    ap.add_argument("--version", required=True)
    ap.add_argument("--platform-tag", required=True,
                    help="wheel platform tag, e.g. manylinux_2_28_x86_64, "
                         "macosx_14_0_arm64, win_amd64")
    ap.add_argument("--licenses-src", default=None,
                    help="prefix with share/<port>/copyright + (windows) bin/ DLLs")
    args = ap.parse_args()
    build_wheel(args.prefix, args.dest_dir, args.version, args.platform_tag,
                args.licenses_src)


if __name__ == "__main__":
    main()
