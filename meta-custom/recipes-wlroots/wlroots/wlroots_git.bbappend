# Enable GBM so the DRM/KMS backend is compiled with buffer allocation support,
# which is required for wlroots to drive a virtio-gpu device under QEMU.
PACKAGECONFIG:append = " gbm"
