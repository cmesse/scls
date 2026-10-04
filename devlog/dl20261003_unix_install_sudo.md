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
| `_uninstall_single_package` | uses `sudo rm` when a target's parent is not writable (first as a separate `_uninstall_single_package_sudo`; merged in the follow-up below) |
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

## Uninstall rules (sudo path first; in-process path since the follow-up below)

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

- ~~The in-process uninstall still has the three defects above.~~ Fixed in the follow-up below
  (Christian: "yes, let's fix that").
- On macOS `--uninstall` reads the Linux manifest (`.so` names), so `.dylib` files are left
  behind. Pre-existing, on both paths.
- Linux unix-mode and a scoped-NOPASSWD sudoers (`dnf`/`apt-get` only) are untested; such a
  rule rejects `sudo install`.

## Follow-up, same day: one uninstall implementation for both paths

Exchange: `tmp/ai_exchange/plan_uninstall_inprocess_fix.md`. Plan audits: Codex (re-run after a
usage-limit failure) and Grok, both approve with changes.

`_uninstall_single_package` now computes one validated target list and removes it either
in-process (`os.unlink`) or with `sudo rm -f`; `_uninstall_single_package_sudo` and the
`shutil.rmtree` body are gone. Rules on both paths: no recursive directory removal, realpath
containment, missing `files/<pkg>.txt` refused, failure returns `False`.

New from the plan audits (both auditors, P1): `files/environment.txt`, `files/libevent.txt` and
`files/hwloc.txt` list their own registry file, so the commit above removed it together with the
other files and a partial failure left the package "not installed" and unretryable. The registry
entry is now excluded from the file list and removed last, only if every file went.

Not changed: `python/scls.py` `_install_direct` / `_install_pkg` continue with the install after a
failed removal ("continuing anyway"), which overwrites the kept registry entry; that file is not
reached from `./scls` (Codex P1, rejected as out of scope).

Diff audits: Codex approve with changes, Grok approve. Applied: `--with-deps` stops at the first
failed package instead of going on to remove its dependencies (Codex P1); a registry file that
vanished counts as removed; a missing `sudo` binary in the directory cleanup is non-fatal.
Residual: a declined sudo password prompts once per chunk of 200 files and once for `rmdir`.

Gate: scratch test, 52/52 — both paths: another package's `share/man/man1` page survives; a
removal failure in the middle (`chflags uchg`) returns `False`, keeps the registry entry, and
the retry succeeds; outside targets and a missing manifest remove nothing.

## Files Updated

`python/build_common.py`, `python/unix_builder.py`, `scls`, `doc/MACOS_BUILD.md`,
`devlog/dl20261003_unix_install_sudo.md`.
