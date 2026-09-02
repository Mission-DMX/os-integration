SUMMARY = "LibreSprite - Animated sprite editor & pixel art tool"
DESCRIPTION = "LibreSprite is a free and open source program for creating and animating your sprites. \
It is a fork of the last GPLv2 commit of Aseprite."
HOMEPAGE = "https://github.com/LibreSprite/LibreSprite"
LICENSE = "GPL-2.0-only"
LIC_FILES_CHKSUM = "file://${S}/LICENSE.txt;md5=b234ee4d69f5fce4486a80fdaf4a4263"

SRC_URI = " \
    gitsm://github.com/LibreSprite/LibreSprite.git;protocol=https;branch=master \
    file://neutral-dark-theme.zip \
    file://pref.xml \
"

SRC_URI[neutral-dark-theme.zip.md5sum] = "e29c3b16f492efb57101e7c036dcaec9"
SRC_URI[neutral-dark-theme.zip.sha256sum] = "6500926a21117c96528955733d3ed354ae9ef5db2e6e38d19b84cbfff5f6c21d"
SRC_URI[pref.xml.md5sum] = "a817af40aa46fbd6e8afe677d4fefa6e"
SRC_URI[pref.xml.sha256sum] = "da9afb9e4f6babdde7c062ea1ed7803cec5b211b4dc8837d52c36f963cc080d0"

SRCREV = "f06050a6227470cc6450a912a0748f6db7ae83a7"
PV = "1.0.0+git${SRCPV}"

S = "${WORKDIR}/git"

DEPENDS = " \
    cmake-native \
    ninja-native \
    curl \
    freetype \
    giflib \
    gtest \
    jpeg \
    pixman \
    libpng \
    libsdl2 \
    libsdl2-image \
    libtinyxml2 \
    libwebp \
    zlib \
    libarchive \
"

inherit cmake pkgconfig

OECMAKE_GENERATOR = "Ninja"
OECMAKE_TARGET_COMPILE = "libresprite"

EXTRA_OECMAKE = " \
    -DCMAKE_BUILD_TYPE=Release \
    -DUSE_SDL2_BACKEND=ON \
    -DWITH_WEBP_SUPPORT=ON \
    -DENABLE_TESTS=OFF \
"

do_configure:prepend() {
    # Upstream pins cmake_minimum_required to 4.1, newer than Yocto's cmake.
    find ${S} -name CMakeLists.txt -exec \
        sed -i 's/cmake_minimum_required(VERSION 4\.1)/cmake_minimum_required(VERSION 3.16)/g' {} +

    # 'gen' is a build-time code generator that must run on the host during
    # do_compile, but the cross-toolchain hardcodes the target's dynamic
    # linker path (/usr/lib/ld-linux-x86-64.so.2) and links against
    # libtinyxml2 from the target sysroot. Since build and target are both
    # x86_64, override the linker and rpath so it runs on the host.
    cat >> ${S}/src/gen/CMakeLists.txt <<EOF

target_link_options(gen PRIVATE
    "-Wl,--dynamic-linker=/lib64/ld-linux-x86-64.so.2"
    "-Wl,-rpath,${RECIPE_SYSROOT}/usr/lib")
EOF
}

do_compile:append() {
    # 'gen' writes the source .xml path (absolute build-tree path) into a
    # comment at the top of every generated header, which trips the
    # 'buildpaths' QA check when they land in -src. Strip the ${S}/ prefix.
    find ${B} \( -name '*.xml.h' -o -name '*.xml.cpp' \) -print0 |
        xargs -0 sed -i "s|${S}/||g"
}

do_install() {
    cd ${B}
    install -d ${D}${bindir}
    install -m 0755 bin/libresprite ${D}${bindir}/libresprite

    install -d ${D}${datadir}/libresprite/data
    cp -r ${S}/data/. ${D}${datadir}/libresprite/data/
    cp ${UNPACKDIR}/pref.xml ${D}${datadir}/libresprite/data/pref.xml

    install -d ${D}${datadir}/libresprite/data/skins/neutral-dark
    install -m 0644 ${UNPACKDIR}/than_dark_theme_libresprite-master/* ${D}${datadir}/libresprite/data/skins/neutral-dark/

    install -d ${D}${datadir}/applications
    cat > ${D}${datadir}/applications/libresprite.desktop << EOF
[Desktop Entry]
Name=LibreSprite
Comment=Animated sprite editor & pixel art tool
Exec=${bindir}/libresprite
Icon=libresprite
Type=Application
Categories=Graphics;RasterGraphics;
EOF

    if [ -f ${B}/bin/libresprite.png ]; then
        install -d ${D}${datadir}/icons/hicolor/256x256/apps
        install -m 0644 ${B}/bin/libresprite.png ${D}${datadir}/icons/hicolor/256x256/apps/libresprite.png
    fi
}

FILES:${PN} = " \
    ${bindir}/libresprite \
    ${datadir}/applications/libresprite.desktop \
    ${datadir}/icons/hicolor/256x256/apps/libresprite.png \
    ${datadir}/libresprite \
"

RDEPENDS:${PN} = " \
    libsdl2 \
    libsdl2-image \
    libpng \
    jpeg \
    zlib \
    freetype \
    giflib \
    libtinyxml2 \
    libarchive \
"
