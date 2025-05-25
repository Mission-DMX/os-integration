inherit python3native

do_install:append() {
    for f in ${D}${bindir}/*.py; do
        sed -i '1s|^#!.*|#!/usr/bin/env python3|' "$f"
    done
}

RDEPENDS:${PN} += "python3-core"
