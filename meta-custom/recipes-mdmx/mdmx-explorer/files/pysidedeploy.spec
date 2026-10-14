[app]
title = mdmx-explorer
project_dir = .
input_file = main.py
project_file =
exec_directory = bin
icon = mdmx-explorer.png

[python]
python_path = .venv/bin/python
packages = Nuitka==2.4.8

[qt]
qml_files =
excluded_qml_plugins =
modules = Core,Gui,Widgets,Svg
plugins = platforms,imageformats,iconengines,styles,platforminputcontexts,wayland-decoration-client,wayland-graphics-integration-client,wayland-shell-integration,xcbglintegrations

[nuitka]
macos.permissions =
mode = standalone
# Keep lxml, package imports, and the mdmx_explorer tree reachable at
# runtime. --static-libpython=no gets appended by the bbclass's sed.
extra_args = --quiet --noinclude-qt-translations --include-package=mdmx_explorer --include-package=lxml
