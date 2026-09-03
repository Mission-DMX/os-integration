SUMMARY = "Simple, portable, and self-contained stacktrace library for C++"
DESCRIPTION = "cpptrace is a lightweight C++ stacktrace library. \
Used by realtime-fish; will be dropped upstream once C++26 stacktrace lands."
HOMEPAGE = "https://github.com/jeremy-rifkin/cpptrace"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://LICENSE;md5=70ee44984c050b4fc6e1da3cc0a5000f"

SRC_URI = "git://github.com/jeremy-rifkin/cpptrace.git;protocol=https;branch=main"
SRCREV = "3db8da80111171c219ab5839905771386bee06b3"
PV = "1.0.4"

DEPENDS = "libdwarf zlib zstd"

inherit cmake

# Use the system libdwarf we just built rather than cpptrace's bundled fetch
EXTRA_OECMAKE = " \
    -DBUILD_SHARED_LIBS=ON \
    -DCPPTRACE_USE_EXTERNAL_LIBDWARF=ON \
    -DCPPTRACE_UNWIND_WITH_LIBUNWIND=OFF \
"
