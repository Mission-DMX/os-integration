.PHONY: init build clean

POKY_DIR := poky
BUILD_DIR := build

init:
	bash -c "cd $(POKY_DIR) && source oe-init-build-env ../$(BUILD_DIR)"

build:
	bash -c "cd $(POKY_DIR) && source oe-init-build-env ../$(BUILD_DIR) && bitbake core-image-minimal"

clean:
	rm -rf $(BUILD_DIR)/tmp $(BUILD_DIR)/cache

