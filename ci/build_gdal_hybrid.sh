#!/bin/bash
# Hybrid build (Linux + macOS): use vcpkg to provide GDAL's C dependencies
# (managed, version-coordinated via the manifest baseline, robust downloads +
# binary caching), then build libgdal itself from source against them. vcpkg
# compiles the deps with the *native* toolchain, so their symbols satisfy the
# manylinux / macOS ABI policies (unlike conda-forge's GCC-15 binaries, which
# auditwheel rejects). Keeps our GDAL version + driver choices + provenance and
# kills the hand-maintained 25-source-download treadmill.
#
# All deps + libgdal are installed into $PREFIX, so the workflow's env/repair use
# a single path on every OS.
#
# Usage: bash ci/build_gdal_hybrid.sh <gdal-version> <gdal-install-prefix>
set -euo pipefail

GDAL_VERSION="${1:?gdal version}"
PREFIX="${2:?install prefix}"
PROJECT="$(pwd)"

# SHA256 pins for the downloads below (supply-chain integrity). Bump GDAL_SRC_SHA256
# whenever GDAL_VERSION changes.
GDAL_SRC_SHA256="1eb8c56a8cea4d3c733d90a719540c1aab981e4eb15e03057092e69b2935ae73"  # gdal 3.13.0
BISON_SHA256="06c9e13bdf7eb24d4ceb6b59205a4f67c2c7e7213119644430fe82fbd14a0abb"     # bison 3.8.2

verify_sha256() {  # <file> <expected>
  echo "$2  $1" | { sha256sum -c - 2>/dev/null || shasum -a 256 -c -; } \
    || { echo "SHA256 mismatch for $1"; exit 1; }
}

OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS-$ARCH" in
  Linux-x86_64)   TRIPLET=x64-linux-dynamic ;;
  Linux-aarch64)  TRIPLET=arm64-linux-dynamic ;;
  Darwin-x86_64)  TRIPLET=x64-osx-dynamic ;;
  Darwin-arm64)   TRIPLET=arm64-osx-dynamic ;;
  *) echo "unsupported $OS-$ARCH"; exit 1 ;;
esac
NPROC="$( (nproc 2>/dev/null) || sysctl -n hw.ncpu )"
# vcpkg's thrift port (Arrow's dep) invokes bison with --file-prefix-map (bison
# >= 3.7). Both distros below ship something older, so we ensure a new bison.
NEED_BISON=1

echo "Installing build prerequisites for $OS..."
if [ "$OS" = "Linux" ]; then
  yum install -y zip unzip tar curl git perl flex bison m4 ninja-build >/dev/null 2>&1 || \
    yum install -y zip unzip tar curl git perl flex bison m4 >/dev/null 2>&1
  bison --version 2>/dev/null | head -1 | grep -qE '3\.(7|8|9|[1-9][0-9])' && NEED_BISON=0
else
  export HOMEBREW_NO_AUTO_UPDATE=1
  brew install autoconf automake libtool pkg-config ninja flex bison >/dev/null 2>&1 || true
  # brew bison/flex are keg-only; put them first on PATH (newer than Apple's).
  export PATH="$(brew --prefix bison)/bin:$(brew --prefix flex)/bin:$PATH"
  NEED_BISON=0
fi

if [ "$NEED_BISON" = "1" ]; then
  echo "Building bison 3.8.2 (system bison too old for thrift)..."
  env -u LD_LIBRARY_PATH curl -fsSL https://ftp.gnu.org/gnu/bison/bison-3.8.2.tar.gz -o bison.tar.gz
  verify_sha256 bison.tar.gz "$BISON_SHA256"
  tar xzf bison.tar.gz
  (cd bison-3.8.2 && ./configure --prefix=/usr/local >/dev/null && make -j"$NPROC" >/dev/null && make install >/dev/null)
  hash -r
fi
command -v ninja >/dev/null 2>&1 || pip install ninja >/dev/null 2>&1 || true

echo "Bootstrapping vcpkg..."
export VCPKG_ROOT="${VCPKG_ROOT:-$PROJECT/vcpkg}"
if [ ! -x "$VCPKG_ROOT/vcpkg" ]; then
  # Full clone (not --depth 1): vcpkg must `git show` the manifest's
  # builtin-baseline commit, which is older than current master HEAD.
  git clone https://github.com/microsoft/vcpkg "$VCPKG_ROOT"
  "$VCPKG_ROOT/bootstrap-vcpkg.sh" -disableMetrics
fi
export VCPKG_DEFAULT_TRIPLET="$TRIPLET"
VCPKG_INSTALLED="$VCPKG_ROOT/installed/$TRIPLET"

echo "Installing C deps via vcpkg ($TRIPLET) from ci/vcpkg.json..."
vcpkg_install() {
  "$VCPKG_ROOT/vcpkg" install \
    --feature-flags="versions,manifests" \
    --x-manifest-root="$PROJECT/ci" \
    --x-install-root="$VCPKG_ROOT/installed" \
    --triplet "$TRIPLET"
}
# vcpkg refuses to retry transient github.com download failures (curl errors 6/7
# -- DNS / connection-refused while fetching boost/* tarballs), which kills the
# whole ~40-min build over a momentary network blip. Retry the install: every
# port already built/downloaded is restored from the binary cache + buildtrees,
# so each attempt only re-fetches what genuinely failed.
vcpkg_ok=0
for attempt in 1 2 3; do
  if vcpkg_install; then vcpkg_ok=1; break; fi
  echo "=== vcpkg install attempt ${attempt}/3 failed; backing off then retrying ==="
  sleep $((attempt * 20))
done
if [ "$vcpkg_ok" -ne 1 ]; then
  echo "=== vcpkg install failed after 3 attempts; dumping recent port build logs ==="
  find "$VCPKG_ROOT/buildtrees" \( -name "*-err.log" -o -name "*-out.log" \) 2>/dev/null \
    | xargs ls -t 2>/dev/null | head -4 \
    | while read -r f; do echo "### $f"; tail -50 "$f"; echo; done
  exit 1
fi

# Stage all deps into $PREFIX so libgdal + its deps + data live in one tree.
echo "Staging vcpkg deps into $PREFIX..."
mkdir -p "$PREFIX"
for d in lib include share bin; do
  [ -d "$VCPKG_INSTALLED/$d" ] && cp -a "$VCPKG_INSTALLED/$d/." "$PREFIX/$d/" 2>/dev/null || true
done

echo "Downloading GDAL ${GDAL_VERSION} source..."
# Clear LD/DYLD library path for this curl: the workflow puts vcpkg's lib dir on
# it, and vcpkg's libcurl (built without all protocols) would shadow the system
# curl and fail with "feature not found" (error 4).
env -u LD_LIBRARY_PATH -u DYLD_LIBRARY_PATH curl -fsSL \
  "https://download.osgeo.org/gdal/${GDAL_VERSION}/gdal-${GDAL_VERSION}.tar.gz" -o gdal-full.tar.gz
verify_sha256 gdal-full.tar.gz "$GDAL_SRC_SHA256"
tar xzf gdal-full.tar.gz
cd "gdal-${GDAL_VERSION}"

OSX_FLAGS=()
if [ "$OS" = "Darwin" ]; then
  OSX_FLAGS=(
    -DCMAKE_OSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET}"
    -DCMAKE_OSX_ARCHITECTURES="${CMAKE_OSX_ARCHITECTURES}"
  )
fi

echo "Building libgdal ${GDAL_VERSION} against the vcpkg deps..."
cmake -S . -B build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" \
    -DVCPKG_TARGET_TRIPLET="$TRIPLET" \
    -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DCMAKE_INSTALL_LIBDIR=lib \
    "${OSX_FLAGS[@]}" \
    -DBUILD_SHARED_LIBS=ON \
    -DBUILD_PYTHON_BINDINGS=OFF \
    -DBUILD_JAVA_BINDINGS=OFF \
    -DBUILD_CSHARP_BINDINGS=OFF \
    -DBUILD_APPS="${GDAL_BUILD_APPS:-OFF}" \
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
    -DGDAL_USE_ARROW=ON \
    -DGDAL_USE_PARQUET=ON \
    -DOGR_ENABLE_DRIVER_ARROW=ON \
    -DOGR_ENABLE_DRIVER_PARQUET=ON \
    -DGDAL_ENABLE_DRIVER_ZARR=ON \
    -DGDAL_USE_EXPAT=ON

cmake --build build -j"$NPROC"
cmake --install build

echo "libgdal built. Version:"
"$PREFIX/bin/gdal-config" --version
