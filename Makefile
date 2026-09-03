.PHONY: run debug build build-debug clean reset-nvram reset-disk

OE_CORE_DIR := openembedded-core
BUILD_DIR := build

# Bridge on the host that qemu should attach the guest NIC to.
BRIDGE ?= virbr0

# OVMF firmware paths on the host. Debian 13 / recent Ubuntu ship the
# split code/vars firmware with a "_4M" suffix (matching the 4 MiB flash
# size). Override on the command line for other distros or older layouts
# (Fedora: /usr/share/edk2/ovmf/OVMF_CODE.fd; older Debian: drop _4M).
OVMF_CODE ?= /usr/share/OVMF/OVMF_CODE_4M.fd
OVMF_VARS ?= /usr/share/OVMF/OVMF_VARS_4M.fd

WIC_IMAGE := $(BUILD_DIR)/tmp/deploy/images/qemux86-64/core-image-minimal-qemux86-64.rootfs.wic
NVRAM := $(BUILD_DIR)/ovmf_vars.fd

# QEMU-only virtual disk: a qcow2 overlay on top of the WIC. The WIC's
# partition layout is fixed at 32 GiB (ESP + rootfsA + rootfsB), which
# means booting it directly in QEMU leaves the firstboot initramfs
# module with no free tail to carve `userdata` from and it fails with
# "No space left on device" during /home + /var seeding. The overlay
# reports a larger virtual size to the guest so sgdisk has real
# headroom; writes land in the qcow2 file, the WIC stays pristine.
QEMU_DISK := $(BUILD_DIR)/qemu-disk.qcow2
QEMU_DISK_SIZE ?= 64G

$(BUILD_DIR)/init:
	echo 0 | sudo tee /proc/sys/kernel/apparmor_restrict_unprivileged_userns || echo "WARN: User NS was not explicetly enabled."
	bash -c "cd $(OE_CORE_DIR) && source oe-init-build-env ../$(BUILD_DIR)"
	rm build/conf/local.conf
	rm build/conf/bblayers.conf
	touch $(BUILD_DIR)/init

build/conf/bblayers.conf: config/bblayers.conf
	cp config/bblayers.conf build/conf/bblayers.conf

build/conf/local.conf: config/local.conf
	cp config/local.conf build/conf/local.conf

build: $(BUILD_DIR)/init build/conf/local.conf build/conf/bblayers.conf
	bash -c "cd $(OE_CORE_DIR) && source oe-init-build-env ../$(BUILD_DIR) && bitbake core-image-minimal"
	xz -f -9 --keep build/tmp/deploy/images/qemux86-64/core-image-minimal-qemux86-64.rootfs.wic

# Produce a WIC that bakes `nokaslr` into GRUB's kernel cmdline so the
# qemu gdb stub can find kernel symbols reliably. Overrides WKS_FILE
# via the environment for a single bitbake invocation.
build-debug: $(BUILD_DIR)/init build/conf/local.conf build/conf/bblayers.conf
	bash -c "cd $(OE_CORE_DIR) && source oe-init-build-env ../$(BUILD_DIR) && WKS_FILE=mdmx-ab-debug.wks.in bitbake core-image-minimal"

clean:
	rm -rf $(BUILD_DIR)

# Fresh copy of writable OVMF NVRAM so EFI variables (boot order, etc.)
# don't leak across sessions and RAUC-style slot experiments start from
# a known state. Run this if a botched run leaves the guest booting into
# UEFI Shell instead of GRUB.
reset-nvram:
	@test -f "$(OVMF_VARS)" || { echo "ERROR: $(OVMF_VARS) not found. Install OVMF (Debian/Ubuntu: apt install ovmf)"; exit 1; }
	cp "$(OVMF_VARS)" "$(NVRAM)"

$(NVRAM): $(OVMF_VARS)
	cp "$(OVMF_VARS)" "$(NVRAM)"

# Wipe the qcow2 overlay so the next `make run` starts from the fresh
# WIC (no userdata partition, no persisted /home or /var state).
reset-disk:
	rm -f $(QEMU_DISK)

$(QEMU_DISK): $(WIC_IMAGE)
	rm -f $(QEMU_DISK)
	qemu-img create -f qcow2 -F raw -b $$(realpath $(WIC_IMAGE)) $(QEMU_DISK) $(QEMU_DISK_SIZE)

#
# If running on a non-nvidia system, use:
#
# -vga none -device virtio-vga \
# -display gtk,show-cursor=on \
#

run: $(NVRAM) $(QEMU_DISK)
	@test -f "$(OVMF_CODE)" || { echo "ERROR: $(OVMF_CODE) not found. Install OVMF (Debian/Ubuntu: apt install ovmf)"; exit 1; }
	@test -f "$(WIC_IMAGE)" || { echo "ERROR: $(WIC_IMAGE) not found. Run 'make build' first."; exit 1; }
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
	-device virtio-net-pci,netdev=mdmx-test-os-iface \
	-drive if=pflash,format=raw,readonly=on,file=$(OVMF_CODE) \
	-drive if=pflash,format=raw,file=$(NVRAM) \
	-drive file=$(QEMU_DISK),if=virtio,format=qcow2

debug: $(NVRAM) $(QEMU_DISK)
	@echo "GDB stub will listen on localhost:1234 (CPU halted at startup)."
	@echo "Attach in a second terminal with:"
	@echo "  gdb $(BUILD_DIR)/tmp/work/qemux86_64-poky-linux/linux-yocto/*/linux-qemux86_64-standard-build/vmlinux"
	@echo "  (gdb) target remote :1234"
	@echo "  (gdb) continue"
	@echo ""
	@echo "NOTE: this target boots the same WIC as 'make run'. If you need"
	@echo "      nokaslr on the kernel cmdline, run 'make build-debug' first"
	@echo "      to rebuild the WIC with mdmx-ab-debug.wks.in."
	@test -f "$(OVMF_CODE)" || { echo "ERROR: $(OVMF_CODE) not found. Install OVMF."; exit 1; }
	@test -f "$(WIC_IMAGE)" || { echo "ERROR: $(WIC_IMAGE) not found. Run 'make build' or 'make build-debug' first."; exit 1; }
	qemu-system-x86_64 -name mission-dmx-os \
	-machine q35 -accel kvm -cpu Skylake-Client-v2 \
	-m 32768 -smp 8,sockets=8,cores=1,threads=1 \
	-audio driver=alsa \
	-device virtio-tablet-pci -device virtio-keyboard-pci \
	-object rng-random,filename=/dev/urandom,id=rng0 -device virtio-rng-pci,rng=rng0 \
	-vga none -device virtio-gpu-pci,xres=1920,yres=1080,edid=on \
	-display gtk,show-cursor=on \
	-serial stdio \
	-netdev bridge,id=mdmx-test-os-iface,br=$(BRIDGE) \
	-device virtio-net-pci,netdev=mdmx-test-os-iface \
	-drive if=pflash,format=raw,readonly=on,file=$(OVMF_CODE) \
	-drive if=pflash,format=raw,file=$(NVRAM) \
	-drive file=$(QEMU_DISK),if=virtio,format=qcow2 \
	-s -S

kernel-config:
	bash -c "cd $(OE_CORE_DIR) && source oe-init-build-env ../$(BUILD_DIR) && bitbake -c menuconfig virtual/kernel && bitbake -c savedefconfig virtual/kernel"
	echo "Please copy generated kernel config (see above) to meta-custom/recipes-kernel/linux/files/defconfig"
