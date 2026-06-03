# Third-Party Notices

This project's own code is licensed under the MIT License (see [`LICENSE`](LICENSE)).

## Bundled native libraries (in the wheels)

The produced wheels bundle GDAL and its C dependencies (PROJ, GEOS, libtiff, curl,
SQLite, libpq, Apache Arrow, OpenJPEG, libpng, libwebp, libxml2, expat, and
others). Each is distributed under its own license — GDAL under its MIT/X11-style
license; the rest under their respective permissive / BSD / MIT / LGPL terms. The
default dependency set is curated to keep the wheels permissively licensed (no GPL
components — e.g. `libpq` is built `--without-readline`).

For compliance, **each bundled library's own license/copyright file is shipped
inside the wheel** at `osgeo/licenses/` (harvested at build time from the vcpkg
`share/<port>/copyright` files). GEOS is LGPL-2.1 and is dynamically linked
(a vendored shared library), satisfying the LGPL relink requirement.

## Acknowledgments

The CI approach here (cibuildwheel-based wheel building, vendoring shared
libraries and GDAL/PROJ data into the wheel) was initially informed by
[rasterio](https://github.com/rasterio/rasterio) (BSD-3-Clause) and
[matthew-brett/multibuild](https://github.com/matthew-brett/multibuild). The
shipping build no longer contains code derived from those projects — it builds
libgdal from source against [vcpkg](https://github.com/microsoft/vcpkg)-provided
dependencies — but credit is due for the original prototype's lineage.
