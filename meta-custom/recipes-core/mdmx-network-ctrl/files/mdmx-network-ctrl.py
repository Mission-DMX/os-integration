#!/usr/bin/python3
"""mdmx-network-ctrl — DBus-driven transient network configuration.

Owns the well-known bus name org.mission_dmx.networking_ctrl on the
system bus at object path / and exposes one method,
ApplyConfiguration(s config_json), described in NetworkControlProtocol.md.

The daemon does not stop systemd-networkd. Instead it materialises the
requested configuration as .network and .netdev drop-ins in
/run/systemd/network/ (a tmpfs, so nothing survives a reboot) with a
name prefix that sorts them ahead of the shipped 20-wired.network, and
restarts systemd-networkd + systemd-resolved so the new configuration
wins. An empty JSON object clears the drop-ins and restores DHCP.
"""

import ipaddress
import json
import subprocess
import sys
from logging import getLogger
from pathlib import Path

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib
from jinja2 import Environment

logger = getLogger(__name__)


BUS_NAME = "org.mission_dmx.networking_ctrl"
OBJECT_PATH = "/"
INTERFACE_NAME = "org.mission_dmx.networking_ctrl"

NETWORKD_RUN_DIR = Path("/run/systemd/network")
RESOLVED_RUN_DIR = Path("/run/systemd/resolved.conf.d")
FILE_PREFIX = "10-mdmx-"
CATCHALL_FILENAME = "15-mdmx-catchall.network"
RESOLVED_DROP_IN = "mdmx.conf"

# Keys reserved at the top level of the JSON payload; everything else is
# taken to be an interface identifier of the form device[.vlan].
RESERVED_KEYS = frozenset({"dw", "dns"})


NETWORK_TEMPLATE = """\
[Match]
Name={{ name }}

{% if mtu is not none -%}
[Link]
MTUBytes={{ mtu }}

{% endif -%}
[Network]
{% if use_dhcp -%}
DHCP=yes
IPv6AcceptRA=yes
{% else -%}
LinkLocalAddressing=no
IPv6AcceptRA=no
{% endif -%}
{% for addr in static_addresses -%}
Address={{ addr }}
{% endfor -%}
{% for child in vlan_children -%}
VLAN={{ child }}
{% endfor %}
{% if default_gateway -%}
[Route]
Gateway={{ default_gateway }}

{% endif -%}
{% for route in routes -%}
[Route]
Destination={{ route.destination }}
{% if route.gateway -%}
Gateway={{ route.gateway }}
{% endif -%}
{% if route.metric is not none -%}
Metric={{ route.metric }}
{% endif %}
{% endfor -%}
"""

NETDEV_VLAN_TEMPLATE = """\
[NetDev]
Name={{ name }}
Kind=vlan

[VLAN]
Id={{ vlan_id }}
"""

STUB_PARENT_TEMPLATE = """\
[Match]
Name={{ name }}

[Network]
LinkLocalAddressing=no
IPv6AcceptRA=no
{% for child in vlan_children -%}
VLAN={{ child }}
{% endfor -%}
"""

CATCHALL_TEMPLATE = """\
[Match]
Name=en* eth*{% for name in excludes %} !{{ name }}{% endfor %}

[Link]
ActivationPolicy=down

[Network]
LinkLocalAddressing=no
IPv6AcceptRA=no
DHCP=no
"""

RESOLVED_TEMPLATE = """\
[Resolve]
DNS={{ servers | join(' ') }}
"""


_jinja = Environment(trim_blocks=False, lstrip_blocks=False,
                     keep_trailing_newline=True)


def _split_iface(name: str) -> tuple[str, int | None]:
    """Split an interface identifier device[.vlan] into (base, vlan_id)."""
    if "." in name:
        base, tag = name.rsplit(".", 1)
        return base, int(tag)
    return name, None


def _remove_transient_files() -> None:
    """Delete every drop-in this daemon may have written previously."""
    NETWORKD_RUN_DIR.mkdir(parents=True, exist_ok=True)
    for path in NETWORKD_RUN_DIR.glob(f"{FILE_PREFIX}*"):
        logger.debug("removing %s", path)
        path.unlink()
    catchall = NETWORKD_RUN_DIR / CATCHALL_FILENAME
    if catchall.exists():
        logger.debug("removing %s", catchall)
        catchall.unlink()
    drop_in = RESOLVED_RUN_DIR / RESOLVED_DROP_IN
    if drop_in.exists():
        logger.debug("removing %s", drop_in)
        drop_in.unlink()


def _pick_gateway_owner(config: dict, gateway: str | None) -> str | None:
    """Choose the interface that will carry the default gateway route.

    Prefer the interface whose configured subnet contains the gateway IP
    (systemd-networkd rejects Gateway= entries that aren't reachable via
    an on-link address); fall back to the first interface with any
    static address; otherwise return None (the gateway is dropped —
    every interface is AUTOMATIC and DHCP will supply its own).
    """
    if not gateway:
        return None
    iface_names = [k for k in config if k not in RESERVED_KEYS]
    try:
        gw_addr = ipaddress.ip_address(gateway)
    except ValueError:
        gw_addr = None

    if gw_addr is not None:
        for name in iface_names:
            for addr in config[name].get("addresses", []):
                if addr == "AUTOMATIC":
                    continue
                try:
                    if gw_addr in ipaddress.ip_interface(addr).network:
                        return name
                except ValueError:
                    continue
    for name in iface_names:
        if any(a != "AUTOMATIC"
               for a in config[name].get("addresses", [])):
            return name
    return None


def _render_iface_network(name: str, iface_cfg: dict,
                          vlan_children: list[str],
                          default_gateway: str | None) -> str:
    addresses = iface_cfg.get("addresses", []) or []
    return _jinja.from_string(NETWORK_TEMPLATE).render(
        name=name,
        mtu=iface_cfg.get("mtu"),
        use_dhcp=any(a == "AUTOMATIC" for a in addresses),
        static_addresses=[a for a in addresses if a != "AUTOMATIC"],
        vlan_children=vlan_children,
        default_gateway=default_gateway,
        routes=iface_cfg.get("routes") or [],
    )


def _write_transient_files(config: dict) -> None:
    """Materialise the parsed configuration into /run drop-ins."""
    NETWORKD_RUN_DIR.mkdir(parents=True, exist_ok=True)

    iface_names = [k for k in config if k not in RESERVED_KEYS]

    # Group VLANs by their base link so each parent's .network file can
    # list its children with VLAN=, and so we know which bases are
    # explicit (won't need a stub) vs. implicit (need a stub .network).
    vlan_children: dict[str, list[str]] = {}
    explicit_bases: set[str] = set()
    for name in iface_names:
        base, vlan_id = _split_iface(name)
        if vlan_id is None:
            explicit_bases.add(name)
        else:
            vlan_children.setdefault(base, []).append(name)

    gateway_owner = _pick_gateway_owner(config, config.get("dw"))

    # .netdev per VLAN.
    for name in iface_names:
        _, vlan_id = _split_iface(name)
        if vlan_id is None:
            continue
        rendered = _jinja.from_string(NETDEV_VLAN_TEMPLATE).render(
            name=name, vlan_id=vlan_id,
        )
        target = NETWORKD_RUN_DIR / f"{FILE_PREFIX}{name}.netdev"
        target.write_text(rendered)
        logger.debug("wrote %s", target)

    # .network per interface actually named in the payload.
    for name in iface_names:
        _, vlan_id = _split_iface(name)
        children = [] if vlan_id is not None else vlan_children.get(name, [])
        rendered = _render_iface_network(
            name=name,
            iface_cfg=config[name],
            vlan_children=children,
            default_gateway=(
                config.get("dw") if name == gateway_owner else None
            ),
        )
        target = NETWORKD_RUN_DIR / f"{FILE_PREFIX}{name}.network"
        target.write_text(rendered)
        logger.debug("wrote %s", target)

    # Stub .network for VLAN parents that weren't listed themselves —
    # networkd won't attach a VLAN child unless the parent link has a
    # matching .network with VLAN= referencing it.
    for base, children in vlan_children.items():
        if base in explicit_bases:
            continue
        rendered = _jinja.from_string(STUB_PARENT_TEMPLATE).render(
            name=base, vlan_children=children,
        )
        target = NETWORKD_RUN_DIR / f"{FILE_PREFIX}{base}.network"
        target.write_text(rendered)
        logger.debug("wrote stub parent %s", target)
        explicit_bases.add(base)

    # Catch-all: unmanage every other en*/eth* link. Sorts after the
    # per-link 10-mdmx-* files (they win by lex order) and before the
    # shipped 20-wired.network (so it wins over DHCP for anything that
    # isn't in the payload).
    excludes = sorted(explicit_bases | set(iface_names))
    rendered = _jinja.from_string(CATCHALL_TEMPLATE).render(excludes=excludes)
    target = NETWORKD_RUN_DIR / CATCHALL_FILENAME
    target.write_text(rendered)
    logger.debug("wrote %s", target)

    # DNS via a systemd-resolved drop-in.
    dns_servers = config.get("dns") or []
    if dns_servers:
        RESOLVED_RUN_DIR.mkdir(parents=True, exist_ok=True)
        rendered = _jinja.from_string(RESOLVED_TEMPLATE).render(
            servers=dns_servers,
        )
        target = RESOLVED_RUN_DIR / RESOLVED_DROP_IN
        target.write_text(rendered)
        logger.debug("wrote %s", target)


def _restart_stack() -> None:
    """Restart networkd + resolved so the /run drop-ins are picked up.

    systemd-networkd's own `networkctl reload` re-reads unit files but
    doesn't reliably re-apply an already-configured link's addresses.
    A full restart is short (~100 ms) and matches the semantic here:
    the caller is explicitly switching profiles.
    """
    for unit in ("systemd-networkd.service", "systemd-resolved.service"):
        result = subprocess.run(
            ["systemctl", "restart", unit],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            logger.error("systemctl restart %s failed: %s",
                         unit, result.stderr.strip())


def _apply(config_json: str) -> None:
    text = (config_json or "").strip()
    config = json.loads(text) if text else {}
    if not isinstance(config, dict):
        raise ValueError("configuration must be a JSON object")

    _remove_transient_files()
    if config:
        logger.info("applying static configuration: %s",
                    sorted(k for k in config if k not in RESERVED_KEYS))
        _write_transient_files(config)
    else:
        logger.info("reverting to DHCP")
    _restart_stack()


class NetworkCtrl(dbus.service.Object):
    def __init__(self, bus, path):
        super().__init__(bus, path)

    @dbus.service.method(INTERFACE_NAME, in_signature="s", out_signature="")
    def ApplyConfiguration(self, config_json):
        try:
            _apply(config_json)
        except (json.JSONDecodeError, ValueError, TypeError,
                AttributeError, KeyError) as exc:
            logger.warning("rejected configuration: %s", exc)
            raise dbus.exceptions.DBusException(
                f"{INTERFACE_NAME}.InvalidConfiguration", str(exc),
            )
        except OSError as exc:
            logger.error("failed to write transient files: %s", exc)
            raise dbus.exceptions.DBusException(
                f"{INTERFACE_NAME}.ApplyFailed", str(exc),
            )


def main() -> int:
    import logging
    # systemd captures stderr; keep the format minimal since journald
    # adds its own timestamp / unit metadata.
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    try:
        bus = dbus.SystemBus()
    except dbus.exceptions.DBusException as exc:
        logger.error("cannot connect to system bus: %s", exc)
        return 1

    try:
        # BusName is stored in a class-level WeakValueDictionary; if we
        # don't keep a strong reference it is garbage-collected right
        # after this call, the name is released, and systemd's Type=dbus
        # startup check then times out. Keep the reference alive for the
        # lifetime of the main loop.
        bus_name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)
    except dbus.exceptions.NameExistsException:
        logger.error("bus name %s is already owned; exiting", BUS_NAME)
        return 1
    except dbus.exceptions.DBusException as exc:
        logger.error("failed to request bus name %s: %s", BUS_NAME, exc)
        return 1

    service = NetworkCtrl(bus, OBJECT_PATH)
    loop = GLib.MainLoop()
    logger.info(
        "listening on %s at %s (bus_name=%r, service=%r)",
        BUS_NAME, OBJECT_PATH, bus_name, service,
    )
    try:
        loop.run()
    except KeyboardInterrupt:
        loop.quit()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logger.exception("mdmx-network-ctrl aborted with an unhandled exception")
        raise
