# Third-party components

This application distributes unmodified runtime libraries from the following projects.
Python package metadata and supplied license files are retained in `_internal/*dist-info/`.
Qt and PySide shared libraries remain separate files and are dynamically loaded.

| Component | Upstream source / attribution | License information |
| --- | --- | --- |
| Python | https://github.com/python/cpython | Python license included in `licenses/PYTHON.txt` |
| Qt / PySide6 / Shiboken6 | https://code.qt.io/cgit/qt/ and https://code.qt.io/cgit/pyside/pyside-setup.git/ | LGPL v3; see included LGPL/GPL texts and https://doc.qt.io/qtforpython-6/licenses.html |
| Qt third-party components | https://doc.qt.io/qt-6.11/licenses-used-in-qt.html | Upstream attribution and source information; Qt version is recorded in build-info.json |
| FFmpeg runtime collected with Qt Multimedia | https://doc.qt.io/qt-6.11/qtmultimedia-attribution-ffmpeg.html | LGPL 2.1 or later and associated upstream notices |
| OpenSSL runtime collected with Python | https://github.com/openssl/openssl | Apache License 2.0; upstream source / notices |
| keyring / pywin32-ctypes / jaraco helpers | https://github.com/jaraco/keyring and their package metadata | Supplied license files in distribution metadata |
| ziamath / ziafont | https://github.com/cdelker/ziamath and https://github.com/cdelker/ziafont | MIT; supplied license files |
| latex2mathml | https://github.com/roniemartinez/latex2mathml | MIT; upstream license |
| STIX Two Math | https://github.com/stipub/stixfonts | SIL Open Font License 1.1; font copyright and metadata in `licenses/FONTS.txt` |
| DejaVu Sans | https://dejavu-fonts.github.io/ | Font copyright and license extracted to `licenses/FONTS.txt` |

The precise installed Python package versions are recorded in `build-info.json`.
Bundled libraries and fonts are not modified by this application's build scripts.
Application source: https://github.com/flandre0605/flandre-notebook

The Inno Setup Chinese translation is from the project-linked user translation,
maintained by Zhenghan Yang (Kira); its original header is retained in the source.
