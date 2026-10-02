# NetBox Interface Hierarchy Tool

A small Python utility for auditing NetBox interface parent relationships and displaying device interfaces in a hierarchical tree.

NetBox stores relationships between physical interfaces and sub-interfaces, but the standard NetBox interface page displays interfaces in a flat table. This script provides a clearer view of those relationships while also checking that sub-interfaces are correctly linked to their physical parent interfaces.

## Features

The script performs two main tasks:

### 1. Parent Interface Audit

The script examines every interface whose name contains a dot (`.`), treating it as a logical sub-interface.

For example:

```text
ge-0/0/0
ge-0/0/0.100
ge-0/0/0.200
```

It expects:

```text
ge-0/0/0.100 -> ge-0/0/0
ge-0/0/0.200 -> ge-0/0/0
```

The audit checks whether each sub-interface:

- Has the correct physical parent configured.
- Has no parent configured.
- Has an incorrect parent configured.
- References a physical interface that does not exist in NetBox.

Example output:

```text
==================================================================
PARENT LINK AUDIT — RMR-PE-TEST
==================================================================
  correctly linked : 15
  missing parent   : 2
  wrong parent     : 1
  no parent exists : 0

    - ge-0/0/0.100          should point to ge-0/0/0
    - ge-0/0/0.200          should point to ge-0/0/0
    ! ge-0/0/1.300          points to ge-0/0/2, expected ge-0/0/1
```

By default, the script performs an audit only and does **not** modify NetBox.

### 2. Interface Tree Report

The script displays interfaces in a parent/child hierarchy instead of NetBox's normal flat interface table.

Example:

```text
==================================================================
INTERFACE TREE — RMR-PE-TEST
==================================================================
ge-0/0/0                   10GBASE-X-SFPP
  ge-0/0/0.100             Virtual
      ip  10.10.100.1/30
  ge-0/0/0.200             Virtual
      ip  10.10.200.1/30
      └─ addresses below this interface: 10.10.100.1/30, 10.10.200.1/30

ge-0/0/1                   10GBASE-X-SFPP
  ge-0/0/1.10              Virtual
      ip  192.168.10.1/24
```

IP addresses remain assigned to their actual logical interfaces in NetBox. The script only rolls them up in the report to make the hierarchy easier to understand.

## Requirements

- Python 3
- NetBox with API access
- A valid NetBox API token
- `requests` Python library

Install the required Python package with:

```bash
pip install requests
```

Alternatively:

```bash
python3 -m pip install requests
```

## Configuration

The script contains a configuration section near the top:

```python
NETBOX_URL = "https://netbox.example.com"
NETBOX_TOKEN = "YOUR_NETBOX_API_TOKEN"
NETBOX_VERIFY_SSL = True

DEVICE_NAME = "RMR-PE-TEST"
```

Update the values before running the script.

### NETBOX_URL

The base URL of the NetBox server.

Example:

```python
NETBOX_URL = "https://netbox.example.com"
```

### NETBOX_TOKEN

A NetBox API token with permission to read:

- Devices
- Interfaces
- IP addresses

If `--fix-parents` is used, the token must also have permission to modify interfaces.

> **Security warning:** Do not commit a real NetBox API token to GitHub, GitLab, or another source-control repository.

For production use, storing the token in an environment variable or secret-management system is recommended.

For example:

```bash
export NETBOX_TOKEN="your-api-token"
```

The Python script can then read it using:

```python
import os

NETBOX_TOKEN = os.environ["NETBOX_TOKEN"]
```

If a token has previously been committed to a public or shared repository, revoke it in NetBox and create a new one.

### NETBOX_VERIFY_SSL

Controls TLS/SSL certificate verification.

Recommended setting:

```python
NETBOX_VERIFY_SSL = True
```

Only disable certificate verification in controlled test environments where necessary.

### DEVICE_NAME

Specify the NetBox device to audit.

Example:

```python
DEVICE_NAME = "RMR-PE-TEST"
```

The device must already exist in NetBox.

## Usage

### Audit Only

Run:

```bash
python netbox_iface_tree.py
```

or:

```bash
python3 netbox_iface_tree.py
```

This mode:

- Queries the device.
- Retrieves its interfaces.
- Retrieves assigned IP addresses.
- Audits sub-interface parent relationships.
- Prints the interface hierarchy.
- Makes **no changes** to NetBox.

This is the recommended mode to run first.

## Fix Missing or Incorrect Parents

Run:

```bash
python netbox_iface_tree.py --fix-parents
```

or:

```bash
python3 netbox_iface_tree.py --fix-parents
```

When this option is enabled, the script updates NetBox through its REST API.

For example, if NetBox contains:

```text
ge-0/0/0
ge-0/0/0.100
```

but `ge-0/0/0.100` has no parent configured, the script will update it to:

```text
ge-0/0/0.100
   parent -> ge-0/0/0
```

Example:

```text
Fixing 2 parent link(s) ...
    linked ge-0/0/0.100 -> ge-0/0/0
    linked ge-0/0/0.200 -> ge-0/0/0
```

After performing the updates, the script retrieves the interfaces again before generating the tree.

## How Parent Interfaces Are Detected

The script uses interface naming conventions.

Any interface containing a dot is considered a sub-interface:

```text
ge-0/0/0.100
xe-0/0/0.200
GigabitEthernet0/0/0.300
TenGigabitEthernet0/1/0.500
```

The physical interface is everything before the first dot.

For example:

```text
ge-0/0/0.100
```

becomes:

```text
Parent: ge-0/0/0
Unit:   100
```

Similarly:

```text
GigabitEthernet0/0/0.250
```

becomes:

```text
Parent: GigabitEthernet0/0/0
Unit:   250
```

## Logical Unit Sorting

Logical units are sorted numerically where possible.

For example:

```text
ge-0/0/0
ge-0/0/0.1
ge-0/0/0.10
ge-0/0/0.100
ge-0/0/0.200
ge-0/0/0.1000
```

This avoids normal string sorting where `.100` might otherwise appear before `.20`.

## NetBox API Endpoints Used

The script interacts with the following NetBox REST API endpoints:

```text
/api/dcim/devices/
/api/dcim/interfaces/
/api/ipam/ip-addresses/
```

When fixing parent relationships, it sends a `PATCH` request to:

```text
/api/dcim/interfaces/<interface-id>/
```

with a payload similar to:

```json
{
  "parent": 123
}
```

where `123` is the NetBox ID of the physical interface.

## Safety

Running:

```bash
python netbox_iface_tree.py
```

is read-only.

Running:

```bash
python netbox_iface_tree.py --fix-parents
```

can modify interface records in NetBox.

Before using `--fix-parents` in production:

- Run the script without the option first.
- Review the proposed parent relationships.
- Confirm that the interface naming convention matches your network.
- Ensure that you have a recent NetBox backup.
- Use a NetBox API token with only the permissions required.

## Assumptions

The script assumes that sub-interfaces follow this format:

```text
<physical-interface>.<logical-unit>
```

Examples:

```text
ge-0/0/0.100
xe-0/0/1.200
GigabitEthernet0/0/0.300
```

It may not correctly determine parent interfaces for platforms using different naming conventions.

For example, interfaces such as:

```text
Vlan100
Port-channel10
Loopback0
Tunnel100
```

are not treated as sub-interfaces because their names do not contain a dot.

This behaviour is intentional.

## Error Handling

The script terminates with an error if:

- The specified device cannot be found.
- The device has no interfaces.
- NetBox returns an HTTP error.
- An interface update fails.

For example:

```text
Device RMR-PE-TEST' not found in NetBox.
```

or:

```text
No interfaces found on RMR-PE-TEST.
```

The script can also be stopped with `Ctrl+C`.

## Recommended Project Structure

```text
netbox-interface-tree/
├── netbox_iface_tree.py
├── README.md
├── requirements.txt
└── .gitignore
```

Example `requirements.txt`:

```text
requests
```

Example `.gitignore`:

```text
.env
__pycache__/
*.pyc
venv/
.venv/
```

## Suggested Future Improvements

Possible enhancements include:

- Move NetBox URL and token to environment variables.
- Accept the device name from the command line.
- Support multiple devices.
- Support sites, tenants, roles, or tags as filters.
- Add a `--dry-run` option for parent repairs.
- Export reports to CSV, JSON, or HTML.
- Add logging.
- Add support for other interface naming conventions.
- Add confirmation before modifying incorrect parent relationships.
- Detect duplicate or conflicting interface definitions.
- Support bulk NetBox API updates.

A future command-line format could look like:

```bash
python netbox_iface_tree.py \
    --device RMR-PE-TEST \
    --fix-parents
```

## Purpose

The main goal of this tool is to make NetBox interface relationships easier to audit and understand without changing how IP addresses are modelled.

It keeps IP addresses attached to their real logical interfaces while presenting a more operationally useful view such as:

```text
Physical Interface
├── Logical Unit
│   └── IP Address
├── Logical Unit
│   └── IP Address
└── Logical Unit
    └── IP Address
```

This can be especially useful for routers and provider-edge devices containing many VLAN-tagged or logical sub-interfaces.

## License

Use and modify this script according to your organisation's internal policies and NetBox access-control requirements.
