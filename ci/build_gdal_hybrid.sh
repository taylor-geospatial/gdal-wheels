#!/bin/bash
# Hybrid build (Linux): use vcpkg to provide GDAL's C dependencies (managed,
# version-coordinated via the manifest baseline, with robust downloads + binary
# caching), then build libgdal itself from source against them. vcpkg compiles
# the deps with the *native manylinux toolchain*, so their symbols satisfy the
# manylinux ABI policy (unlike conda-forge's GCC-15 binaries, which auditwheel
# rejects). Keeps our GDAL version + driver choices + provenance; kills the
# hand-maintained 25-source-download treadmill.
#
# Usage: bash ci/build_gdal_hybrid.sh <gdal-version> <gdal-install-prefix>
set -euo pipefail

GDAL_VERSION="${1:?gdal version}"
PREFIX="${2:?install prefix}"
PROJECT="$(pwd)"

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)  TRIPLET=x64-linux-dynamic ;;
  aarch64) TRIPLET=arm64-linux-dynamic ;;
  *) echo "unsupported arch $ARCH"; exit 1 ;;
esac

echo "Installing vcpkg build prerequisites..."
# flex+bison are needed by vcpkg's thrift port (Arrow's dep); vcpkg expects them
# from the system package manager on Linux.
yum install -y zip unzip tar curl git perl flex bison ninja-build >/dev/null 2>&1 || \
  yum install -y zip unzip tar curl git perl flex bison >/dev/null 2>&1
command -v ninja >/dev/null 2>&1 || pip install ninja >/dev/null 2>&1 || true

echo "Bootstrapping vcpkg..."
export VCPKG_ROOT=/opt/vcpkg
if [ ! -x "$VCPKG_ROOT/vcpkg" ]; then
  # Full clone (not --depth 1): vcpkg must be able to `git show` the manifest's
  # builtin-baseline commit, which is older than current master HEAD.
  git clone https://github.com/microsoft/vcpkg "$VCPKG_ROOT"
  "$VCPKG_ROOT/bootstrap-vcpkg.sh" -disableMetrics
fi
export VCPKG_DEFAULT_TRIPLET="$TRIPLET"
export VCPKG_INSTALLED="$VCPKG_ROOT/installed/$TRIPLET"

echo "Installing C deps via vcpkg ($TRIPLET) from ci/vcpkg.json..."
if ! "$VCPKG_ROOT/vcpkg" install \
    --feature-flags="versions,manifests" \
    --x-manifest-root="$PROJECT/ci" \
    --x-install-root="$VCPKG_ROOT/installed" \
    --triplet "$TRIPLET"; then
  echo "=== vcpkg install failed; dumping recent port build logs ==="
  find "$VCPKG_ROOT/buildtrees" -name "*-err.log" -o -name "*-out.log" 2>/dev/null \
    | xargs ls -t 2>/dev/null | head -4 \
    | while read -r f; do echo "### $f"; tail -50 "$f"; echo; done
  exit 1
fi

echo "Downloading GDAL ${GDAL_VERSION} source..."
# Clear LD_LIBRARY_PATH for this curl: the workflow puts vcpkg's lib dir on it,
# and vcpkg's libcurl (built without all protocols) would otherwise be loaded by
# the system curl and fail with "feature not found" (error 4).
env -u LD_LIBRARY_PATH curl -fsSL "https://download.osgeo.org/gdal/${GDAL_VERSION}/gdal-${GDAL_VERSION}.tar.gz" -o gdal-full.tar.gz
tar xzf gdal-full.tar.gz
cd "gdal-${GDAL_VERSION}"

echo "Building libgdal ${GDAL_VERSION} against the vcpkg deps..."
cmake -S . -B build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" \
    -DVCPKG_TARGET_TRIPLET="$TRIPLET" \
    -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DCMAKE_INSTALL_LIBDIR=lib \
    -DBUILD_SHARED_LIBS=ON \
    -DBUILD_PYTHON_BINDINGS=OFF \
    -DBUILD_JAVA_BINDINGS=OFF \
    -DBUILD_CSHARP_BINDINGS=OFF \
    -DBUILD_APPS=OFF \
    -DGDAL_USE_JXL=OFF \
    -DGDAL_BUILD_OPTIONAL_DRIVERS=ON \
    -DOGR_BUILD_OPTIONAL_DRIVERS=ON \
    -DGDAL_USE_GEOS=ON \
    -DGDAL_USE_CURL=ON \
    -DGDAL_USE_TIFF=ON \
    -DGDAL_USE_GEOTIFF_INTERNAL=ON \
    -DGDAL_USE_SQLITE3=ON \
    -DOGR_ENABLE_DRIVER_GPKG=ON \
    -DGDAL_USE_OPENJPEG=ON \
    -DGDAL_USE_PNG=ON \
    -DGDAL_USE_JPEG=ON \
    -DGDAL_USE_WEBP=ON \
    -DGDAL_USE_ZSTD=ON \
    -DGDAL_USE_LERC=ON \
    -DGDAL_USE_POSTGRESQL=ON \
    -DOGR_ENABLE_DRIVER_PG=ON \
    -DGDAL_USE_ARROW=OFF \
    -DGDAL_ENABLE_DRIVER_ZARR=ON \
    -DGDAL_USE_EXPAT=ON

cmake --build build -j"$(nproc)"
cmake --install build

echo "libgdal built. Version:"
"$PREFIX/bin/gdal-config" --version
# Record the vcpkg dep lib dir for the repair step (LD_LIBRARY_PATH / data).
echo "$VCPKG_INSTALLED" > /tmp/vcpkg_installed_dir.txt
