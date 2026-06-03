#!/bin/bash
# Build libgdal from source on Windows (MSVC) so its version matches the 3.13.0
# Python bindings. vcpkg supplies the C dependencies via its CMake toolchain;
# we only build GDAL itself here. Run from git-bash with the MSVC env active.
#
# Usage: bash ci/build_gdal_windows.sh <gdal-version> <vcpkg-triplet> <install-prefix>
set -euo pipefail

GDAL_VERSION="${1:?gdal version}"
TRIPLET="${2:?vcpkg triplet}"
PREFIX="${3:?install prefix}"

VCPKG_ROOT="${VCPKG_INSTALLATION_ROOT:-C:/vcpkg}"
TOOLCHAIN="${VCPKG_ROOT}/scripts/buildsystems/vcpkg.cmake"
VCPKG_INSTALLED="${VCPKG_ROOT}/installed/${TRIPLET}"

echo "Building libgdal ${GDAL_VERSION} (${TRIPLET}) -> ${PREFIX}"
echo "vcpkg toolchain: ${TOOLCHAIN}"

curl -fsSL "https://download.osgeo.org/gdal/${GDAL_VERSION}/gdal-${GDAL_VERSION}.tar.gz" -o gdal-full.tar.gz
tar xzf gdal-full.tar.gz
cd "gdal-${GDAL_VERSION}"

cmake -S . -B build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_TOOLCHAIN_FILE="${TOOLCHAIN}" \
    -DVCPKG_TARGET_TRIPLET="${TRIPLET}" \
    -DCMAKE_INSTALL_PREFIX="${PREFIX}" \
    -DCMAKE_PREFIX_PATH="${VCPKG_INSTALLED}" \
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
    -DOGR_ENABLE_DRIVER_SQLITE=ON \
    -DOGR_ENABLE_DRIVER_GPKG=ON \
    -DGDAL_USE_OPENJPEG=ON \
    -DGDAL_USE_PNG=ON \
    -DGDAL_USE_JPEG=ON \
    -DGDAL_USE_WEBP=ON \
    -DGDAL_USE_ZSTD=ON \
    -DGDAL_USE_LERC=ON \
    -DGDAL_USE_LIBLZMA=ON \
    -DGDAL_USE_LIBXML2=ON \
    -DGDAL_USE_PCRE2=ON \
    -DGDAL_USE_EXPAT=ON \
    -DGDAL_USE_POSTGRESQL=ON \
    -DOGR_ENABLE_DRIVER_PG=ON \
    -DGDAL_ENABLE_DRIVER_POSTGISRASTER=ON \
    -DGDAL_USE_ARROW=ON \
    -DGDAL_USE_PARQUET=ON \
    -DOGR_ENABLE_DRIVER_ARROW=ON \
    -DOGR_ENABLE_DRIVER_PARQUET=ON \
    -DGDAL_ENABLE_DRIVER_ZARR=ON \
    -DGDAL_USE_HDF5=OFF \
    -DGDAL_USE_NETCDF=OFF

cmake --build build --config Release
cmake --install build

echo "libgdal installed. Contents of ${PREFIX}/bin (gdal dll):"
ls "${PREFIX}/bin" | grep -i gdal || true
"${PREFIX}/bin/gdalinfo" --version || true
