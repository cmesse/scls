# Googletest Changelog

## Version 1.18.0-1 - Tue Aug 18 2026
- Updated to version 1.18.0
- Clear CPATH for this recipe's build. gcc searches CPATH ahead of -isystem
  directories, and upstream declares gtest's interface includes SYSTEM, so an
  already-installed gtest 1.17.0 under the prefix shadowed the in-tree 1.18.0
  headers and gmock failed to compile against the older ABI. googletest needs
  nothing from the prefix, so blanking CPATH is safe.
  See devlog/dl20260827_googletest_cpath_header_shadowing.md.

## Version 1.17.0 - Wed Dec 10 2025
- initial build
