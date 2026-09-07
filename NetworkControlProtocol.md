# Network Control DBUS Protocol

## Bus endpoint

The daemon owns the well-known bus name `org.mission_dmx.networking_ctrl` on
the **system bus** and exposes an object at path `/` implementing the
interface `org.mission_dmx.networking_ctrl` with a single method:

    ApplyConfiguration(s config_json) -> nothing

`config_json` is a JSON document (see below). Passing an empty JSON object
(`{}`) — or the empty string — reverts the system to the default,
DHCP-driven configuration managed by `systemd-networkd`.

If a network device (or VLAN) is not in the configuration message, it is
taken down.

## Message format

The top-level JSON value is an object. Two reserved keys carry global
settings:

  - `"dw"` — default gateway, IPv4 or IPv6 address as string (optional; if
    absent, no default route is installed)
  - `"dns"` — list of DNS server addresses as strings (optional)

Any other key is treated as an interface identifier in the notation
`device[.vlan]` (e.g. `eth0`, `eth0.100`). Its value is an object with the
following fields:

  - `"addresses"` — list of strings. Each entry is either a CIDR address
    (e.g. `"192.168.1.10/24"`, `"2001:db8::1/64"`) or the literal
    `"AUTOMATIC"`, meaning DHCPv4 + SLAAC + DHCPv6 should be used for this
    interface. At most one `"AUTOMATIC"` entry per interface.
  - `"mtu"` — integer MTU in bytes (optional; if absent, the kernel/link
    default is kept)
  - `"routes"` — list of route objects (optional). Each route object has:
      * `"destination"` — CIDR of the route target (string, required)
      * `"gateway"` — next-hop address (string, optional; if absent, the
        route is on-link on this interface)
      * `"metric"` — integer route metric (optional)

## Example

```json
{
  "dw": "192.168.1.1",
  "dns": ["192.168.1.1", "1.1.1.1"],
  "eth0": {
    "addresses": ["192.168.1.10/24"],
    "mtu": 1500,
    "routes": [
      {"destination": "10.0.0.0/8", "gateway": "192.168.1.254"}
    ]
  },
  "eth0.100": {
    "addresses": ["10.100.0.5/24"]
  }
}
```

Sending `{}` afterwards returns the system to DHCP on all interfaces
matched by the default `20-wired.network` profile.
