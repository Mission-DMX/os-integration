.PHONY: init build clean

init:
	bash -c "source poky/oe-init-build-env ../build"

build:
	bash -c "source poky/oe-init-build-env ../build && bitbake core-image-minimal"

clean:
	rm -rf build/tmp
