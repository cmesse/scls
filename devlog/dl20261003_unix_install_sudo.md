# Devlog 2026-10-03 — unix_builder install/uninstall escalate with sudo on an unwritable prefix

**Date:** 2026-10-03
**Topic:** `./scls install <pkg>` on the non-RPM/DEB path failed with `PermissionError` when the
prefix is root-owned (`/opt/scls` on macOS). The builder now checks writability and publishes
with sudo; `--uninstall` does the same. Exchange: `tmp/ai_exchange/plan_unix_install_sudo.md`.
**AIs involved:** Claude Fable 5.1 (macOS dev host); Codex gpt-5.6-terra and Grok 4.7 — round 1
on the plan (`high`), round 2 on the diff (`xhigh`), both blind.
**Flavor / Host:** `macos`, x86_64, prefix `/opt/scls` (root:wheel, 37836 entries, none owned by
the build user).
**Verification:** real sudo — Christian ran `./scls install spral`: files root:wheel, registry
entry written, dylib id `/opt/scls/lib/libspral.dylib`, nothing root-owned under `work/`. That
run predates the round-2 adjustments. Scratch test with a `sudo` PATH shim against locked temp
prefixes, real BSD `install`/`ln`/`rm`/`rmdir`: 39/39 checks after the adjustments; generated
(`environment`) path equal to the in-process result in content, modes and order.
`py_compile`, `bash -n scls`. **Not run:** Linux unix-mode (GNU coreutils, `secure_path`), real
sudo for `--uninstall`, `install_generated` and `scls build all`. RPM and DEB builders are
unchanged; reviewed, not built.

## Decisions (Christian)

- "I would like the builder to check if the target directory is writable, and ask for sudo if not."
- "We can also make the --uninstall flag work symmetrically."

## What changed

| where | change |
|---|---|
| `python/build_common.py` | new block *Privileged publish*: `paths_need_sudo`, `publish_needs_sudo`, `prefix_needs_sudo`, `run_sudo`, `sudo_publish_tree`, `sudo_write_registry_entry` |
| `write_registry_entry` | new keyword `output_root=None` (write location only; reads stay on `prefix`). No existing caller passes it |
| `uninstall_package` | returns `False` when any package's step fails (it returned `True` unconditionally) |
| `_uninstall_single_package` | branches to `_uninstall_single_package_sudo` when a target's parent is not writable |
| `python/unix_builder.py` | `install()`: per-destination preflight, then sudo publish or the unchanged in-process loop; `final_post` via `sudo /bin/sh -c`; `install_name_tool` via sudo; registry via `sudo_write_registry_entry`. `install_generated()`: renders into `work_dir/generated-stage` and publishes it when `install_root == self.prefix` is unwritable |
| `scls` | keepalive block factored into `start_sudo_keepalive`; `build all` in unix mode calls it when `prefix_needs_sudo` |

Design rules, from the two plan audits and `scripts/build_libhsl.py:635-650`:

- Only individual commands run as root (`install`, `ln`, `rm`, `rmdir`, `install_name_tool`,
  the final-post shell). Python is never re-executed under sudo, so `work/` and `__pycache__`
  stay user-owned.
- A writable prefix keeps the previous code path. `DebBuilder` stages into a destdir and can
  never escalate (`install_root != self.prefix`).
- The check is per destination, before anything is written: a user-owned prefix with a
  root-owned subtree escalates instead of failing mid-copy.
- Before the first sudo command: no destination may be an existing directory; every write
  directory (and the registry directory) must resolve inside the prefix. `lib -> lib64` passes,
  a symlink leading out of the prefix is refused.
- File modes go to `install -m` as octal text; setuid/setgid bits are dropped (files become
  root-owned). `-p` keeps mtime as `copy2` does.
- The build `PATH` is not forwarded into the root shell for final-post hooks. The only hook
  (`recipes/gcc.yaml:153`, macOS) needs `/usr/bin/install_name_tool` only.

## Uninstall under sudo differs from the in-process path, deliberately

- **No recursive directory removal.** `share/man/man1` is a manifest line in 15 `files/*.txt`
  (`man3`: 5, `man7`: 3, `man5`: 2). Removing it recursively deletes every package's pages.
  The sudo path removes files and symlinks only and leaves directories to the empty-directory
  cleanup. On this host no manifest directory line lacks listed children, so that is complete.
- **Containment.** Every existing target's parent must resolve inside the prefix, else nothing
  is removed and the uninstall fails. `get_package_files` passes a manifest line that does not
  start with `%{prefix}` through verbatim.
- **Failure is failure.** A failed `rm`, a refused target or a missing `files/<pkg>.txt` returns
  `False`, exit 1.

## Open Questions

- **The in-process uninstall still has the three defects above** (recursive removal of shared
  man directories when run as root or on a user-owned prefix, no containment, warn-and-succeed).
  Both auditors recommended fixing it; it was left untouched because the approval covered the
  sudo behaviour. Needs Christian's decision.
- On macOS `--uninstall` reads the Linux manifest (`.so` names), so `.dylib` files are left
  behind. Pre-existing, on both paths.
- Linux unix-mode and a scoped-NOPASSWD sudoers (`dnf`/`apt-get` only) are untested; such a
  rule rejects `sudo install`.

## Files Updated

`python/build_common.py`, `python/unix_builder.py`, `scls`, `doc/MACOS_BUILD.md`,
`devlog/dl20261003_unix_install_sudo.md`.
