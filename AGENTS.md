
This project build firmware based on yocto for an embedded system with touch screens attached.

## General instructions
Avoid adding new dependencies globally but add them to existing recipies first if possible.

## Tool usage
The image can be testes using make debug on the local host. This spawns a GDB server that can be attached to as well as a console.
Use the following tools through ssh on the host 141.83.158.129 within the os-integration directory. The local changes to the recipies are automatically synced to this host.
Use `make build` to build the image.
Use `make clean` to clean the entire image.
Use `bash -c "cd poky && source oe-init-build-env ../build && bitbake -c cleansstate <package>"` to clean a specific `<package>`.


