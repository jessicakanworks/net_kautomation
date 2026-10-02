"""
NetBox interface hierarchy tool.

Two jobs:
  1. AUDIT/FIX  — make sure every sub-interface (name contains a dot) has its
     `parent` field pointing at the matching physical interface in NetBox.
  2. REPORT     — print the interface list as a tree, with IP addresses rolled
     up under each physical interface, which the NetBox UI does not do.

Usage:
    python netbox_iface_tree.py
    python netbox_iface_tree.py --fix-parents

Requires:
    pip install requests python-dotenv
"""

import argparse
import os
import sys
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv


# Load configuration from .env
load_dotenv()

NETBOX_URL = os.getenv("NETBOX_URL")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN")
DEVICE_NAME = os.getenv("DEVICE_NAME")
NETBOX_VERIFY_SSL = os.getenv("NETBOX_VERIFY_SSL", "true").strip().lower() in {
    "1", "true", "yes", "on"
}
NETBOX_TIMEOUT = int(os.getenv("NETBOX_TIMEOUT", "20"))


def validate_config():
    required = {
        "NETBOX_URL": NETBOX_URL,
        "NETBOX_TOKEN": NETBOX_TOKEN,
        "DEVICE_NAME": DEVICE_NAME,
    }

    missing = [name for name, value in required.items() if not value]

    if missing:
        sys.exit(
            "Missing required environment variable(s): "
            + ", ".join(missing)
            + "\nCopy .env.example to .env and fill in the required values."
        )


class NetBoxClient:
    def __init__(self, base_url, token, verify_ssl=True, timeout=20):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Token {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        self.session.verify = verify_ssl
        self.timeout = timeout

    def _url(self, path):
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def get_all(self, path, params=None):
        results, params = [], dict(params or {})
        params.setdefault("limit", 1000)
        url = self._url(path)

        while url:
            r = self.session.get(url, params=params, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            results.extend(data["results"])
            url = data.get("next")
            params = None

        return results

    def patch(self, path, payload):
        r = self.session.patch(
            self._url(path),
            json=payload,
            timeout=self.timeout,
        )

        if r.status_code >= 400:
            raise RuntimeError(
                f"PATCH {path} failed [{r.status_code}]: {r.text}"
            )

        return r.json()


def is_sub(name):
    return "." in name


def parent_name(name):
    return name.split(".", 1)[0]


def unit_number(name):
    """Sort key for logical units: numeric where possible."""
    if not is_sub(name):
        return -1

    unit = name.split(".", 1)[1]

    try:
        return int(unit)
    except ValueError:
        return 1 << 30


def sort_key(name):
    """Group by parent, physical first, then logical units in order."""
    return (parent_name(name), unit_number(name))


def audit_parents(nb, ifaces, fix=False):
    """Check that every sub-interface points at its physical parent."""
    by_name = {i["name"]: i for i in ifaces}
    missing, wrong, ok, orphaned = [], [], 0, []

    for iface in ifaces:
        name = iface["name"]

        if not is_sub(name):
            continue

        expected = by_name.get(parent_name(name))

        if not expected:
            orphaned.append(name)
            continue

        current = iface.get("parent")
        current_id = current["id"] if isinstance(current, dict) else None

        if current_id is None:
            missing.append((iface, expected))
        elif current_id != expected["id"]:
            wrong.append((iface, current, expected))
        else:
            ok += 1

    print("=" * 66)
    print(f"PARENT LINK AUDIT — {DEVICE_NAME}")
    print("=" * 66)
    print(f"  correctly linked : {ok}")
    print(f"  missing parent   : {len(missing)}")
    print(f"  wrong parent     : {len(wrong)}")
    print(f"  no parent exists : {len(orphaned)}")

    for iface, expected in missing:
        print(
            f"    - {iface['name']:<22} "
            f"should point to {expected['name']}"
        )

    for iface, current, expected in wrong:
        cur = current.get("name") if isinstance(current, dict) else current
        print(
            f"    ! {iface['name']:<22} points to {cur}, "
            f"expected {expected['name']}"
        )

    for name in orphaned:
        print(
            f"    ? {name:<22} physical interface "
            f"{parent_name(name)} not in NetBox"
        )

    todo = missing + [(i, e) for i, _c, e in wrong]

    if not todo:
        print("\n  Nothing to fix.")
        return

    if not fix:
        print(
            f"\n  {len(todo)} link(s) could be fixed. "
            "Re-run with --fix-parents."
        )
        return

    print(f"\n  Fixing {len(todo)} parent link(s) ...")

    for iface, expected in todo:
        nb.patch(
            f"/api/dcim/interfaces/{iface['id']}/",
            {"parent": expected["id"]},
        )
        print(f"    linked {iface['name']} -> {expected['name']}")


def print_tree(ifaces, ips_by_iface_id):
    """Render the hierarchical view NetBox's flat table does not provide."""
    by_name = {i["name"]: i for i in ifaces}
    children = {}
    roots = []

    for iface in ifaces:
        name = iface["name"]

        if is_sub(name) and parent_name(name) in by_name:
            children.setdefault(parent_name(name), []).append(iface)
        else:
            roots.append(iface)

    print("\n" + "=" * 66)
    print(f"INTERFACE TREE — {DEVICE_NAME}")
    print("=" * 66)

    def fmt(iface, indent):
        name = iface["name"]
        pad = "  " * indent
        enabled = "" if iface.get("enabled", True) else "  [disabled]"
        desc = iface.get("description") or ""
        desc = f'  "{desc}"' if desc else ""
        itype = (iface.get("type") or {}).get("label", "")

        line = (
            f"{pad}{name:<{26 - 2 * indent}} "
            f"{itype:<22}{desc}{enabled}"
        )
        print(line.rstrip())

        for ip in ips_by_iface_id.get(iface["id"], []):
            print(f"{pad}    ip  {ip}")

    for root in sorted(roots, key=lambda i: sort_key(i["name"])):
        fmt(root, 0)

        kids = sorted(
            children.get(root["name"], []),
            key=lambda i: sort_key(i["name"]),
        )

        for kid in kids:
            fmt(kid, 1)

        child_ips = [
            ip
            for kid in kids
            for ip in ips_by_iface_id.get(kid["id"], [])
        ]

        if child_ips and not ips_by_iface_id.get(root["id"]):
            joined = ", ".join(child_ips)
            print(f"      └─ addresses below this interface: {joined}")

        print()


def main():
    validate_config()

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--fix-parents",
        action="store_true",
        help="Backfill missing/incorrect parent links in NetBox.",
    )
    args = ap.parse_args()

    nb = NetBoxClient(
        NETBOX_URL,
        NETBOX_TOKEN,
        verify_ssl=NETBOX_VERIFY_SSL,
        timeout=NETBOX_TIMEOUT,
    )

    devices = nb.get_all(
        "/api/dcim/devices/",
        params={"name": DEVICE_NAME},
    )

    if not devices:
        sys.exit(f"Device '{DEVICE_NAME}' not found in NetBox.")

    dev_id = devices[0]["id"]

    ifaces = nb.get_all(
        "/api/dcim/interfaces/",
        params={"device_id": dev_id},
    )

    if not ifaces:
        sys.exit(f"No interfaces found on {DEVICE_NAME}.")

    ips = nb.get_all(
        "/api/ipam/ip-addresses/",
        params={"device_id": dev_id},
    )

    ips_by_iface_id = {}

    for ip in ips:
        assigned = ip.get("assigned_object") or {}
        iface_id = assigned.get("id")

        if iface_id:
            ips_by_iface_id.setdefault(iface_id, []).append(ip["address"])

    audit_parents(nb, ifaces, fix=args.fix_parents)

    if args.fix_parents:
        ifaces = nb.get_all(
            "/api/dcim/interfaces/",
            params={"device_id": dev_id},
        )

    print_tree(ifaces, ips_by_iface_id)

    print(
        f"Totals: {len(ifaces)} interfaces, "
        f"{len(ips)} IP addresses"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
