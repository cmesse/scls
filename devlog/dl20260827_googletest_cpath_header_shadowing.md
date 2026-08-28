# 2026-08-27 — googletest 1.18.0 gmock build failure: CPATH shadows -isystem

## Purpose

`./scls build googletest` fails on the gmock translation unit with several dozen
compiler errors that look like a broken source tarball or an unsupported
compiler. It is neither. This note records the actual mechanism — a gcc include
search-order interaction that is **not** specific to googletest — the one-line
recipe fix, and how to recognise the same failure in another package.

Diagnosed on the Ubuntu 24.04 build host, debug flavor, gcc 13.3.0, upgrading
an installed googletest 1.17.0 to 1.18.0.

## Symptom

`make -j8` fails compiling `googlemock/src/gmock-all.cc`. The errors come in
four flavors, all pointing into the *source tree's* gmock headers:

```
gmock-actions.h:1867:36: error: expected constructor, destructor, or type
    conversion before '(' token
 1867 | GTEST_INTERNAL_DEPRECATE_AND_INLINE("Avoid using DoAll() ...")

gmock-matchers.h:4977:59: error: 'StringType' is not a member of
    'testing::internal'; did you mean 'StringLike'?

gmock-spec-builders.h:1533:19: error: 'class testing::internal::MutexBase' has
    no member named 'unlock'; did you mean 'Unlock'?

gmock-spec-builders.cc:215:23: error: no matching function for call to
    'testing::internal::GTestMutexLock::GTestMutexLock(testing::internal::Mutex&)'
```

The tell is in the `note:` line that accompanies the last one:

```
/opt/scls/debug/include/gtest/internal/gtest-port.h:1732:12: note: candidate: ...
```

An **installed** header under the prefix is participating in the build of a
package that has its own copy of that header in-tree. `gtest` itself builds
fine and only gmock fails, because gmock is the target that consumes gtest's
headers across a target boundary.

## Root cause

gcc's `#include <...>` search order is:

1. `-I` directories, in command-line order
2. directories from `CPATH` / `CPLUS_INCLUDE_PATH`
3. `-isystem` directories
4. standard system directories

`CPATH` outranks `-isystem`. Both halves of the collision follow:

**Half one — SCLS puts the prefix on CPATH.** `setup_environment()`
(`python/build_common.py:952`) does `_prepend('CPATH', f"{prefix}/include")`
for every package on every flavor. This is deliberate and load-bearing for the
rest of the stack.

**Half two — googletest hands its own headers to gmock as SYSTEM includes.**
Upstream's `googletest/CMakeLists.txt:141` declares the gtest target's interface
includes with `target_include_directories(gtest SYSTEM INTERFACE ...)`, so the
generated flags for gmock are:

```
CXX_INCLUDES = -I.../googlemock/include -I.../googlemock \
               -isystem .../googletest/include -isystem .../googletest
```

gmock's *own* includes are plain `-I` (and so beat CPATH, which is why the
gmock headers found are the in-tree 1.18.0 ones), but gtest's are `-isystem`
(and so lose to CPATH, which is why the gtest headers found are the installed
1.17.0 ones). Every error above is a 1.18.0-source-against-1.17.0-header
mismatch:

| Error | 1.17.0 installed header | 1.18.0 source header |
|---|---|---|
| `GTEST_INTERNAL_DEPRECATE_AND_INLINE` not a macro | absent | defined in `gtest-port.h` |
| `StringType` not a member of `testing::internal` | absent | `gtest-matchers.h:833` |
| `ImplicitCastEqMatcher` not declared | absent | `gtest-matchers.h:788` |
| `MutexBase` has no `lock`/`unlock` | `Lock()` / `Unlock()` | `lock()` / `unlock()` |
| `GTestMutexLock(MutexBase&)` no match | ctor takes `MutexBase*` (line 1732) | ctor takes `MutexBase&` (line 1769) |

Each row was checked by grepping the installed 1.17.0 headers under
`/opt/scls/debug/include/gtest/` against the extracted 1.18.0 tree.

Reproduce the ordering in isolation — no googletest needed:

```
$ CPATH=/opt/scls/debug/include g++ -E -x c++ /dev/null \
      -isystem /path/to/googletest-1.18.0/googletest/include -v
#include <...> search starts here:
 /opt/scls/debug/include                      <-- CPATH
 /path/to/googletest-1.18.0/googletest/include  <-- -isystem, loses
```

## Fix

`recipes/googletest.yaml` clears `CPATH` for its own build:

```yaml
configure:
  type: cmake
  env:
    CPATH: ""
```

Safe because googletest is self-contained: it compiles nothing against the
prefix (`requires:` is `cmake` alone, and `features:` are all false). Verified
that an empty `CPATH` adds *no* directory — gcc does not expand `CPATH=""` to
`"."`, unlike the empty-element behaviour that `build_common.py:942-944` warns
about for `LIBRARY_PATH`:

```
$ CPATH= g++ -E -x c++ /dev/null -v   # search list starts at /usr/include/c++/13
```

`configure.env` reaches all three builders, so the knob is live everywhere:
`build_common.setup_environment()` applies recipe env at line 975, *after* the
CPATH prepend at 952; `rpm_builder.get_configure_env_vars()` emits
`export CPATH=` into the SPEC.

## Verification

Ubuntu 24.04, debug flavor, `./scls build googletest`:

- build log prints `Setting CPATH=`
- `googlemock/CMakeFiles/gmock.dir/flags.make` unchanged (still `-isystem`) —
  the fix is in the environment, not in the flags
- all four libraries built: `libgtest.so.1.18.0`, `libgtest_main.so.1.18.0`,
  `libgmock.so.1.18.0`, `libgmock_main.so.1.18.0`
- `work/pkgs/scls-debug-googletest_1.18.0-1_amd64.deb` created, source package
  and `dpkg-source -x` replay check both pass

**Not verified:** the RPM path. This host cannot run `rpmbuild`. The mechanism
is the same `configure.env` knob and rpm_builder renders it as a plain
`export CPATH=`, but that is reasoned, not run. Also not verified: whether the
installed 1.17.0 was the *only* stale header set involved — the build now
succeeds, which is the operative evidence, but the prefix was not emptied and
retested.

The package was built, not installed. `./scls install googletest` still needs to
run to displace 1.17.0 from the prefix.

## Diagnosing this class of failure elsewhere

The signature is: **a compiler error in package X's own source, whose `note:`
lines cite a header under `/opt/scls/<flavor>/include` belonging to package X.**
It only bites on an in-place *upgrade* where the ABI moved — a first-ever build
has nothing installed to shadow with, and a same-version rebuild shadows with an
identical header and compiles clean. That makes it look version-specific when it
is really upgrade-specific.

To confirm on any host, read the generated flags for the failing target:

```
grep CXX_INCLUDES <builddir>/<target>.dir/flags.make
```

If the directory holding the correct headers appears after `-isystem` rather
than `-I`, CPATH wins and this is the same bug.

Only cmake projects that explicitly mark their interface includes `SYSTEM` are
exposed; plain `target_include_directories()` emits `-I`, which outranks CPATH.
So this is not a stack-wide hazard — it is a hazard for the specific upstreams
that opt into SYSTEM includes for their own headers.

## Deliberately not done

**Changing `setup_environment()` to stop putting the prefix on CPATH.** That
prepend is how most of the stack finds its dependencies' headers during
configure probes; removing or reordering it to fix one recipe would be a
stack-wide behavioural change validated by a single package. The per-recipe
opt-out is the proportionate fix.

**Uninstalling 1.17.0 before building.** It would have made this build pass, but
leaves the recipe broken for the next person on a host that still has the old
package, and quietly makes googletest un-upgradable-in-place.

## Open questions

1. **Do `ucx`, `vtk`, or any other cmake recipe mark interface includes SYSTEM?**
   Not surveyed. A `grep -rn 'SYSTEM' ` across extracted sources at build time
   would answer it, but the failure is self-announcing (see signature above), so
   a pre-emptive sweep may not be worth it.
2. **Should `configure.env` support a delete/unset operation?** Setting a var to
   the empty string happens to be harmless for `CPATH`, but the same trick on
   `LIBRARY_PATH` would inject `.` per the existing warning in
   `build_common.py:942-944`. A recipe needing to *unset* rather than blank a
   path variable currently has no way to say so. See the comment at
   `build_common.py:942-944`.
3. **RPM-path confirmation.** Needs one `./scls build googletest` on a
   RedHat-family host with 1.17.0 installed, to confirm `export CPATH=` in the
   generated SPEC has the same effect.
