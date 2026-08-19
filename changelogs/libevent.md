# Libevent Changelog

## Version 2.1.13-1 - Tue Aug 18 2026
- Updated to version 2.1.13
- Dropped libevent-ssl-test-use-sha256.patch: upstream 2.1.13 makes the same
  change itself (test/regress_ssl.c now signs the test cert with EVP_sha256),
  so the patch no longer applies.

## Version 2.1.12-1 - Mon Dec 15 2025
- Updated to version 2.1.12

