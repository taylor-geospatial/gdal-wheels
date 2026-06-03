#!/bin/bash
# Download GDAL's official PyPI *sdist* (the pip-ready, pre-generated package:
# real setup.py + pre-generated SWIG *_wrap.cpp, no swig needed) and extract it
# to ./gdal-src so cibuildwheel can build it.
#
# We rename the distribution from "GDAL" -> "gdal-wheels" (the PyPI name "GDAL"
# is owned by OSGeo). The import package stays "osgeo", so this remains a
# drop-in: `pip install gdal-wheels` then `from osgeo import gdal`.
#
# Usage: bash ci/fetch_gdal_src.sh 3.13.0
set -euo pipefail

GDAL_VERSION="${1:?usage: fetch_gdal_src.sh <gdal-version>}"
DIST_NAME="gdal-wheels"
OUT_DIR="gdal-src"

echo "Fetching GDAL ${GDAL_VERSION} sdist from PyPI..."
rm -rf "${OUT_DIR}" _gdal_sdist
mkdir -p _gdal_sdist

# Resolve the sdist URL via the PyPI JSON API and download it directly. We do
# NOT use `pip download`, because pip may try to *build* the sdist to resolve
# metadata, which fails before libgdal exists.
sdist_url="$(python - "${GDAL_VERSION}" <<'PY'
import json, sys, urllib.request
ver = sys.argv[1]
with urllib.request.urlopen(f"https://pypi.org/pypi/GDAL/{ver}/json") as r:
    data = json.load(r)
urls = [u["url"] for u in data["urls"] if u["packagetype"] == "sdist"]
if not urls:
    sys.exit(f"no sdist found for GDAL=={ver}")
print(urls[0])
PY
)"
echo "  sdist: ${sdist_url}"
curl -fsSL "${sdist_url}" -o "_gdal_sdist/gdal-${GDAL_VERSION}.tar.gz"

echo "Extracting..."
tar xzf "_gdal_sdist/gdal-${GDAL_VERSION}.tar.gz"
mv "gdal-${GDAL_VERSION}" "${OUT_DIR}"
rm -rf _gdal_sdist

# --- Rename distribution GDAL -> gdal-wheels (setup.py + pyproject.toml) ---
echo "Renaming distribution to '${DIST_NAME}'..."
python - "${OUT_DIR}" "${DIST_NAME}" <<'PY'
import re, sys, pathlib
root, dist = pathlib.Path(sys.argv[1]), sys.argv[2]

setup_py = root / "setup.py"
s = setup_py.read_text()
# `name = 'GDAL'` (module-level, consumed by setup(name=name))
s2 = re.sub(r"^name\s*=\s*['\"]GDAL['\"]", f"name = '{dist}'", s, count=1, flags=re.M)
assert s2 != s, "did not find `name = 'GDAL'` in setup.py"
setup_py.write_text(s2)

pyproject = root / "pyproject.toml"
p = pyproject.read_text()
p2 = re.sub(r'^name\s*=\s*"GDAL"', f'name = "{dist}"', p, count=1, flags=re.M)
assert p2 != p, "did not find `name = \"GDAL\"` in pyproject.toml"
# GDAL's sdist declares requires-python >=3.8, which makes cibuildwheel try to
# build 3.8-3.11 too; those fail because GDAL build-requires setuptools>=77
# (which dropped <3.12). We only target 3.12+, so raise the floor here.
p3 = re.sub(r'^requires-python\s*=\s*"[^"]*"', 'requires-python = ">=3.12"', p2, count=1, flags=re.M)
assert p3 != p2, "did not find `requires-python` in pyproject.toml"
pyproject.write_text(p3)
print(f"  setup.py + pyproject.toml renamed to {dist}, requires-python >=3.12")
PY

# Copy our build helpers inside the package source too, so the cibuildwheel
# repair command can find them via {project}/ci regardless of how cibuildwheel
# resolves {project} when package-dir is set.
mkdir -p "${OUT_DIR}/ci" "${OUT_DIR}/tests"
cp ci/patch_wheel.py ci/runtime_shim.py "${OUT_DIR}/ci/"
cp tests/test_smoke.py tests/test_functional.py "${OUT_DIR}/tests/"

echo "Done. Package source ready at ${OUT_DIR}/ (setup.py present: $([ -f ${OUT_DIR}/setup.py ] && echo yes || echo NO))"
