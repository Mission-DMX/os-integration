.PHONY: run build clean

POKY_DIR := poky
BUILD_DIR := build

$(BUILD_DIR)/init: clean
	echo 0 | sudo tee /proc/sys/kernel/apparmor_restrict_unprivileged_userns
	bash -c "cd $(POKY_DIR) && source oe-init-build-env ../$(BUILD_DIR)"
	rm build/conf/local.conf
	rm build/conf/bblayers.conf
	touch $(BUILD_DIR)/init

build/conf/bblayers.conf: config/bblayers.conf
	cp config/bblayers.conf build/conf/bblayers.conf

build/conf/local.conf: config/local.conf
	cp config/local.conf build/conf/local.conf

build: $(BUILD_DIR)/init build/conf/local.conf build/conf/bblayers.conf
	bash -c "cd $(POKY_DIR) && source oe-init-build-env ../$(BUILD_DIR) && bitbake core-image-minimal"

clean:
	rm -rf $(BUILD_DIR)

run:
	qemu-system-x86_64 -name mission-dmx-os \
	-machine pc-q35-jammy-hpb -accel kvm -cpu Skylake-Client-v2 \
	-m 32768 -smp 8,sockets=8,cores=1,threads=1 \
	-audio driver=alsa \
	-usb -device usb-tablet -usb -device usb-kbd \
	-object rng-random,filename=/dev/urandom,id=rng0 -device virtio-rng-pci,rng=rng0 \
	-display gtk,gl=on,show-cursor=on \
	-netdev user,id=mdmx-test-os-iface \
	-drive file=$(BUILD_DIR)/tmp/deploy/images/qemux86-64/core-image-minimal-qemux86-64.rootfs.ext4,if=virtio,format=raw \
	-kernel $(BUILD_DIR)/tmp/deploy/images/qemux86-64/bzImage-qemux86-64.bin \
	-append "root=/dev/hda"
	
# 
