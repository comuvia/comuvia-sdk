# Security policy

## Supported versions

| Version | Status |
|---|---|
| 0.1.x | Alpha. Security reports are accepted |

This project is maintained by Comuvia LLC. There is no guaranteed response or fix time.

## Reporting a vulnerability

Please report privately, not in a public issue. Use GitHub private vulnerability reporting: on [github.com/comuvia/comuvia-sdk](https://github.com/comuvia/comuvia-sdk), open **Security**, then **Report a vulnerability**.

If you cannot use GitHub, email info@comuvia.com with "security" in the subject line. Reports sent there are read manually.

Please include the affected package and version, what an attacker could do, and steps or a minimal synthetic reproduction. Do not send real personal data, credentials or other secrets.

Fixes are released as new versions and described in the changelog; a GitHub security advisory may also be published.

## Scope

In scope: the `comuvia` and `foreglass` packages and the tools in this repository. Examples:

- input that the strict parser or the validator should refuse but accepts;
- record-store damage that `store verify` misses, beyond its documented detection limit;
- `foreglass` requests outside its documented hosts, ports, redirect limit, size cap or deadline;
- file writes outside the directory a caller chose.

Out of scope: the services that publish the ForeGlass artifacts, and the documented limitations in each package README.
