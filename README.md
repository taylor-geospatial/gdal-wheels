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

## Command-line tools (opt-in)

The base wheel ships only the Python `osgeo` bindings, to stay lean. If you also
want GDAL's compiled C command-line tools (`gdalinfo`, `ogr2ogr`, `ogrinfo`,
`gdalwarp`, `gdal_translate`, `gdalbuildvrt`, `gdaladdo`, `gdalsrsinfo`, the
unified `gdal` app, …) on your `PATH`, install the companion distribution:

```bash
pip install gdal-wheels-tools     # then: gdalinfo --version, ogr2ogr ...
```

`gdal-wheels-tools` is **self-contained**: it vendors its own copy of libgdal +
the C stack next to the binaries (RPATH / `@loader_path` on Linux/macOS,
adjacent DLLs on Windows), so the tools work with or without the base wheel and
never depend on a system GDAL. The tradeoff is a duplicated lib stack
(~25–35 MB per platform); that is why the tools are a separate opt-in wheel
rather than bundled into the base. Built by `ci/build_tools_wheel.py` from the
same libgdal build.

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
