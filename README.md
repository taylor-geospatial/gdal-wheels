# gdal-wheels

Standalone binary wheels for the GDAL Python API (`osgeo`).

```bash
pip install gdal-wheels        # then: from osgeo import gdal, ogr, osr
```

The official `GDAL` package on PyPI is source-only and fails without a matching
system libgdal. These wheels bundle libgdal 3.13.0 + its C stack (PROJ, GEOS,
Arrow/Parquet, PostgreSQL, …) and the GDAL/PROJ data, so they install and import
with no system GDAL on Linux, macOS, and Windows.

Published as `gdal-wheels` (the `GDAL` name is owned by OSGeo); the import package
is still `osgeo`, so it's a drop-in replacement.

## How it works

GitHub Actions builds libgdal + its C deps from source (vcpkg on Windows),
cibuildwheel builds GDAL's SWIG bindings against it, and the libs + data are
vendored into each wheel. Bump `GDAL_VERSION` in
[`.github/workflows/build-wheels.yaml`](.github/workflows/build-wheels.yaml) to
ship a new GDAL.

## License

MIT ([`LICENSE`](LICENSE)). GDAL and the bundled C deps keep their own (permissive/
BSD/MIT/LGPL) licenses, shipped inside the wheel at `osgeo/licenses/`. See
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
