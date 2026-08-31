# Security policy

Please do not report suspected credential exposure in a public issue. Contact the repository maintainer privately and revoke the affected credential immediately.

The app is intentionally read-only:

- Trading 212 credentials should have account and portfolio read permissions only.
- The codebase does not call a broker order endpoint.
- Secret defaults are empty and Home Assistant renders secret options as password fields.
- API credentials are not included in dashboard output, research evidence, or normal logs.

Home Assistant administrators and anyone with host-level access may be able to read app configuration. Protect the Home Assistant account, backups, and host accordingly.
