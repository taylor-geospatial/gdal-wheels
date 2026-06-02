# Third-Party Notices

This project's own code is licensed under the MIT License (see [`LICENSE`](LICENSE)).
Portions of it are derived from third-party open-source projects, whose notices
and licenses are reproduced below as required.

---

## rasterio

The C-dependency build recipe [`ci/config.sh`](ci/config.sh) — and the overall
cibuildwheel-based wheel-building approach — is derived from
[rasterio](https://github.com/rasterio/rasterio) (its `ci/config.sh`), which is
itself derived from [matthew-brett/multibuild](https://github.com/matthew-brett/multibuild)
and [rasterio/rasterio-wheels](https://github.com/rasterio/rasterio-wheels).

rasterio is distributed under the BSD-3-Clause license:

```
Copyright (c) 2013-2021, Mapbox
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of Mapbox nor the names of its contributors may
  be used to endorse or promote products derived from this software without
  specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL <COPYRIGHT HOLDER> BE LIABLE FOR ANY DIRECT,
INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

---

## Bundled native libraries (in the wheels)

The produced wheels bundle GDAL and its C dependencies (PROJ, GEOS, libtiff,
curl, SQLite, libpq, Apache Arrow, and others). Each is distributed under its
own license (GDAL: MIT/X11-style; the others under their respective permissive /
LGPL terms). The default driver/dependency set is chosen to keep the wheels
permissively licensed. See the GDAL documentation for the authoritative list of
included drivers and their dependency licenses.
