#!/bin/bash
# Hybrid build (Linux/macOS): install GDAL's C dependencies as PREBUILT,
# version-coordinated conda-forge binaries via micromamba, then build only
# libgdal itself from source against them. This keeps our GDAL version + driver
# choices + provenance, while killing the ~25-source-download maintenance
# treadmill. The deps + libgdal land in $PREFIX (used as the install prefix and
# the dep search root), so the rest of the pipeline (gdal-config, auditwheel/
# delocate) works unchanged.
#
# Usage: bash ci/build_gdal_hybrid.sh <gdal-version> <prefix>
set -euo pipefail

GDAL_VERSION="${1:?gdal version}"
PREFIX="${2:?install prefix}"

OS="$(uname -s)"; ARCH="$(uname -m)"
case "$OS-$ARCH" in
  Linux-x86_64)   MAMBA_PLATFORM=linux-64 ;;
  Linux-aarch64)  MAMBA_PLATFORM=linux-aarch64 ;;
  Darwin-x86_64)  MAMBA_PLATFORM=osx-64 ;;
  Darwin-arm64)   MAMBA_PLATFORM=osx-arm64 ;;
  *) echo "unsupported $OS-$ARCH"; exit 1 ;;
esac

# Download the GDAL source FIRST, with the system curl. micromamba below puts a
# conda curl on PATH (we prepend $PREFIX/bin) that can lack protocols, so any
# curl after env creation may fail.
echo "Downloading GDAL ${GDAL_VERSION} source..."
curl -fsSL "https://download.osgeo.org/gdal/${GDAL_VERSION}/gdal-${GDAL_VERSION}.tar.gz" -o gdal-full.tar.gz
tar xzf gdal-full.tar.gz

echo "Installing conda-forge C deps ($MAMBA_PLATFORM) into $PREFIX via micromamba..."
mkdir -p "$PREFIX"
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-/tmp/mamba-root}"
curl -Ls "https://micro.mamba.pm/api/micromamba/${MAMBA_PLATFORM}/latest" | tar -xj -C /tmp bin/micromamba
MAMBA=/tmp/bin/micromamba

# GDAL's build/runtime C dependencies (NOT gdal itself): conda-forge resolves a
# mutually-compatible set. --only-deps applies to the whole spec list, so install
# the build tools (cmake/ninja/pkg-config) in a separate, normal step.
"$MAMBA" create -y -p "$PREFIX" -c conda-forge "libgdal" --only-deps
"$MAMBA" install -y -p "$PREFIX" -c conda-forge cmake ninja pkg-config

echo "Building libgdal ${GDAL_VERSION} from source against the conda deps..."
cd "gdal-${GDAL_VERSION}"

export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
"$PREFIX/bin/cmake" -S . -B build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DCMAKE_PREFIX_PATH="$PREFIX" \
    -DBUILD_SHARED_LIBS=ON \
    -DBUILD_PYTHON_BINDINGS=OFF \
    -DBUILD_JAVA_BINDINGS=OFF \
    -DBUILD_CSHARP_BINDINGS=OFF \
    -DGDAL_BUILD_OPTIONAL_DRIVERS=ON \
    -DOGR_BUILD_OPTIONAL_DRIVERS=ON \
    -DGDAL_USE_GEOS=ON \
    -DGDAL_USE_CURL=ON \
    -DGDAL_USE_TIFF=ON \
    -DGDAL_USE_GEOTIFF_INTERNAL=ON \
    -DGDAL_USE_SQLITE3=ON \
    -DOGR_ENABLE_DRIVER_GPKG=ON \
    -DGDAL_USE_HDF5=ON \
    -DGDAL_USE_NETCDF=ON \
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

"$PREFIX/bin/cmake" --build build -j"$(nproc 2>/dev/null || sysctl -n hw.ncpu)"
"$PREFIX/bin/cmake" --install build

echo "libgdal built. Version:"
"$PREFIX/bin/gdal-config" --version
