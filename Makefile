.PHONY: run debug build clean

POKY_DIR := poky
BUILD_DIR := build

$(BUILD_DIR)/init:
	echo 0 | sudo tee /proc/sys/kernel/apparmor_restrict_unprivileged_userns || echo "WARN: User NS was not explicetly enabled."
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

#
# If running on a non-nvidia system, use:
#
# -vga none -device virtio-vga \
# -display gtk,show-cursor=on \
#

run:
	qemu-system-x86_64 -name mission-dmx-os \
	-machine q35 -accel kvm -cpu Skylake-Client-v2 \
	-m 32768 -smp 8,sockets=8,cores=1,threads=1 \
	-audio driver=alsa \
	-device virtio-tablet-pci -device virtio-keyboard-pci \
	-object rng-random,filename=/dev/urandom,id=rng0 -device virtio-rng-pci,rng=rng0 \
	-vga none -device virtio-gpu-pci,xres=1920,yres=1080,edid=on \
	-display gtk,show-cursor=on \
	-serial stdio \
	-netdev user,id=mdmx-test-os-iface \
	-drive file=$(BUILD_DIR)/tmp/deploy/images/qemux86-64/core-image-minimal-qemux86-64.rootfs.ext4,if=virtio,format=raw \
	-kernel $(BUILD_DIR)/tmp/deploy/images/qemux86-64/bzImage-qemux86-64.bin \
	-append "root=/dev/vda"

debug:
	@echo "GDB stub will listen on localhost:1234 (CPU halted at startup)."
	@echo "Attach in a second terminal with:"
	@echo "  gdb $(BUILD_DIR)/tmp/work/qemux86_64-poky-linux/linux-yocto/*/linux-qemux86_64-standard-build/vmlinux"
	@echo "  (gdb) target remote :1234"
	@echo "  (gdb) continue"
	@echo ""
	qemu-system-x86_64 -name mission-dmx-os \
	-machine q35 -accel kvm -cpu Skylake-Client-v2 \
	-m 32768 -smp 8,sockets=8,cores=1,threads=1 \
	-audio driver=alsa \
	-device virtio-tablet-pci -device virtio-keyboard-pci \
	-object rng-random,filename=/dev/urandom,id=rng0 -device virtio-rng-pci,rng=rng0 \
	-vga none -device virtio-gpu-pci,xres=1920,yres=1080,edid=on \
	-display gtk,show-cursor=on \
	-serial stdio \
	-netdev user,id=mdmx-test-os-iface \
	-drive file=$(BUILD_DIR)/tmp/deploy/images/qemux86-64/core-image-minimal-qemux86-64.rootfs.ext4,if=virtio,format=raw \
	-kernel $(BUILD_DIR)/tmp/deploy/images/qemux86-64/bzImage-qemux86-64.bin \
	-append "root=/dev/vda nokaslr" \
	-s -S

kernel-config:
	bash -c "cd $(POKY_DIR) && source oe-init-build-env ../$(BUILD_DIR) && bitbake -c menuconfig virtual/kernel && bitbake -c savedefconfig virtual/kernel"
	echo "Please copy generated kernel config (see above) to meta-custom/recipes-kernel/linux/files/defconfig"

# 
