#!/usr/bin/env python3
"""Build a private libhsl for Ipopt's runtime loader from a licensee's own HSL tarballs.

HSL is proprietary (STFC HSL licence). SCLS never ships, stages, or commits HSL
source or anything built from it; only these scripts are public. A licensee runs
this against the original tarballs they obtained themselves, and gets a shared
library that the stack's unchanged libipopt can dlopen:

    hsllib /home/<you>/.local/scls-hsl/<flavor>/lib/libhsl.so
    linear_solver ma97

Tarballs to provide, and usage: doc/HSL_BUILD.md.

Pipeline (todo/libhsl_source_selection.md §9):
  1. scripts/hsl/assemble_sources.sh: Coin-HSL base + verified standalone overrides
     (today HSL_MA77 6.5.0) into one tree outside the work tree, with LICENCES/ and
     PROVENANCE.txt.
  2. scripts/hsl/CMakeLists.txt: build libcoinhsl with the flavor's compilers,
     flags and BLAS/LAPACK line, against the stack's METIS (Coin-HSL's own METIS 5
     adapter), then `cmake --install` into a staging directory.
  3. Self-check on the staged library, and only then publish it to --prefix:
       - every symbol Ipopt's HSL loader resolves; no METIS defined inside
       - every DT_NEEDED resolves where the flavor says (stack METIS/BLAS, MKL)
       - dlopen smoke test
       - MA77 factor-and-solve (scripts/hsl/tests/ma77_factor_solve.c); its
         refactorization part runs only when HSL_MA77 >= 6.5.0 is present
       - check_mkl_linkage.sh on MKL flavors
"""

import argparse
import atexit
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HSL_DIR = REPO / 'scripts' / 'hsl'
sys.path.insert(0, str(REPO / 'python'))

from build_common import load_flavor  # noqa: E402
from math_common import compiler_family, get_math_link_line, openmp_flag  # noqa: E402

# Directories of a full Coin-HSL tree, in the order its meson.build adds them
# (coinhsl meson.build: dirs = common, ma27, ma28, mc19 + the full-install set).
COINHSL_DIRS = ['common', 'ma27', 'ma28', 'mc19',
                'hsl_ma77', 'hsl_ma86', 'hsl_ma97', 'hsl_mc68', 'ma57']

# The METIS 5 path of Coin-HSL's metis/meson.build. Fixed rather than parsed:
# that file chooses between three alternatives, and we always want this one.
METIS5_SOURCES = ['metis/metis5_adapter.c', 'metis/metis5.f90']

# Symbols libipopt 3.14 resolves through its HSL loader (upstream
# src/Algorithm/LinearSolvers/Ip*SolverInterface.cpp, IpMc19TSymScalingMethod.cpp).
# F77 routines carry gfortran's trailing underscore; the HSL_* C interfaces do not.
IPOPT_SYMBOLS = [
    'ma27ad_', 'ma27bd_', 'ma27cd_', 'ma27id_',
    'ma57ad_', 'ma57bd_', 'ma57cd_', 'ma57ed_', 'ma57id_',
    'mc19ad_',
    'ma77_default_control_d', 'ma77_open_nelt_d', 'ma77_open_d', 'ma77_input_vars_d',
    'ma77_input_reals_d', 'ma77_analyse_d', 'ma77_factor_d', 'ma77_factor_solve_d',
    'ma77_solve_d', 'ma77_resid_d', 'ma77_scale_d', 'ma77_enquire_posdef_d',
    'ma77_enquire_indef_d', 'ma77_alter_d', 'ma77_restart_d', 'ma77_finalise_d',
    'ma86_default_control_d', 'ma86_analyse_d', 'ma86_factor_d',
    'ma86_factor_solve_d', 'ma86_solve_d', 'ma86_finalise_d',
    'ma97_default_control_d', 'ma97_analyse_d', 'ma97_factor_d',
    'ma97_factor_solve_d', 'ma97_solve_d', 'ma97_finalise_d', 'ma97_free_akeep_d',
    'mc68_default_control_i', 'mc68_order_i',
]

FILES_RE = re.compile(r"\bsrc\s*\+=\s*files\(([^)]*)\)", re.S)
QUOTED_RE = re.compile(r"'([^']+)'")


CLEANUP_DIR = None   # scratch dir holding HSL sources; removed at exit unless --keep-work.
                     # Only ever a directory THIS run created (mkdtemp, or a --work-dir that did
                     # not exist), and only registered after every path check has passed, so no
                     # exit path can remove a pre-existing directory of the user's.


def cleanup() -> None:
    global CLEANUP_DIR
    if CLEANUP_DIR and Path(CLEANUP_DIR).exists():
        shutil.rmtree(CLEANUP_DIR, ignore_errors=True)
    CLEANUP_DIR = None


atexit.register(cleanup)                       # normal exit, sys.exit, uncaught exception
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))   # route SIGTERM through atexit


def die(msg: str) -> None:
    print(f"build_libhsl: error: {msg}", file=sys.stderr)
    cleanup()
    sys.exit(1)


RUN_ENV = None  # set in main(): os.environ with <stack>/bin first on PATH


def run(cmd, cwd=None, env=None, capture=False):
    cmd = [str(c) for c in cmd]
    env = env if env is not None else RUN_ENV
    printable = shlex.join(cmd)
    print(f"+ {printable}" if len(printable) < 400 else f"+ {printable[:400]} ...")
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=capture, text=True)
    if result.returncode != 0:
        if capture:
            sys.stderr.write(result.stdout + result.stderr)
        die(f"command failed ({result.returncode}): {cmd[0]}")
    return result.stdout if capture else ''


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def active_flavor() -> str:
    conf = REPO / 'flavor.conf'
    if conf.exists():
        for line in conf.read_text().splitlines():
            m = re.match(r"\s*flavor:\s*(\S+)", line)
            if m:
                return m.group(1)
    die("no --flavor given and flavor.conf has no flavor: entry")


def manifest(src: Path) -> list:
    """Source files from the tree's own meson.build files, in meson's order."""
    files = []
    for d in COINHSL_DIRS:
        if not (src / d).is_dir():
            die(f"{d}/ missing: not a full Coin-HSL tree")
        for mb in (src / d / 'meson.build', src / d / 'C' / 'meson.build'):
            if not mb.exists():
                continue
            # Drop meson comments first: hsl_mc68/meson.build keeps a commented-out
            # `src += files('hsl_mc68i.f90')` because that module is already in
            # common/deps90.f90, and compiling it twice defines it twice.
            text = re.sub(r"#[^\n]*", "", mb.read_text())
            for block in FILES_RE.findall(text):
                for name in QUOTED_RE.findall(block):
                    files.append(mb.parent / name)
    files += [src / f for f in METIS5_SOURCES]
    missing = [str(f.relative_to(src)) for f in files if not f.exists()]
    if missing:
        die(f"manifest names files that are not in the tree: {missing}")
    if not any(f.name == 'deps90.f90' for f in files):
        die("common/deps90.f90 not in the manifest: meson.build layout changed")
    return files


def cmake_quote(s: str) -> str:
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace(';', '\\;') + '"'


def git_blob(path: Path) -> str:
    try:
        blob = subprocess.run(['git', '-C', REPO, 'hash-object', path],
                              capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(['git', '-C', REPO, 'status', '--porcelain', '--', path],
                               capture_output=True, text=True, check=True).stdout.strip()
        return f"{blob}{' (uncommitted)' if dirty else ''}"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 'unknown'


def gfortran_major(fc: str) -> int:
    out = run([fc, '-dumpversion'], capture=True).strip()
    try:
        return int(out.split('.')[0])
    except ValueError:
        return 0


def resolved_needed(lib: Path, is_macos: bool) -> dict:
    """soname -> resolved path ('' if not found)."""
    out = run(['otool', '-L', lib] if is_macos else ['ldd', lib], capture=True)
    res = {}
    for line in out.splitlines()[1 if is_macos else 0:]:
        line = line.strip()
        if is_macos:
            p = line.split(' (')[0]
            res[Path(p).name] = p
        elif '=>' in line:
            name, rest = (x.strip() for x in line.split('=>', 1))
            res[name] = '' if rest.startswith('not found') else rest.split(' (')[0]
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--sources', type=Path, default=None,
                    help='directory holding the original HSL tarballs (never downloaded); '
                         'default: tmp/HSL under the SCLS checkout if it exists')
    ap.add_argument('--flavor', default=None, help='SCLS flavor (default: flavor.conf)')
    ap.add_argument('--prefix', type=Path, default=None,
                    help='install prefix (default: ~/.local/scls-hsl/<flavor>)')
    ap.add_argument('--work-dir', type=Path, default=None,
                    help='scratch directory for sources and build (default: new dir in $TMPDIR)')
    ap.add_argument('--keep-work', action='store_true',
                    help='keep the scratch directory (it contains HSL sources: never share it)')
    ap.add_argument('--install-stack', action='store_true',
                    help='install into the stack prefix (/opt/scls/<flavor>) instead of a per-user '
                         'prefix, so Ipopt finds libhsl.so through its own RUNPATH with no hsllib '
                         'option. Shows the HSL licence texts from your tarballs and requires '
                         'acceptance (or --accept-licence); publishes with sudo if needed. '
                         'This is `./scls install hsl`.')
    ap.add_argument('--accept-licence', action='store_true',
                    help='non-interactive acceptance for a shared install (--install-stack, or a --prefix '
                         'outside your home). You confirm that you have read your HSL licence agreement '
                         'and that it covers use of the library at that location by everyone who can '
                         'use it.')
    ap.add_argument('--no-overrides', action='store_true',
                    help='build Coin-HSL as shipped, without standalone overrides (for comparison)')
    ap.add_argument('--jobs', type=int, default=os.cpu_count() or 1)
    args = ap.parse_args()

    if args.sources is None:
        # tmp/ is git-ignored; it is where a licensee drops the tarballs by hand.
        if (REPO / 'tmp' / 'HSL').is_dir():
            args.sources = REPO / 'tmp' / 'HSL'
        else:
            die("no --sources given and tmp/HSL does not exist; point --sources at the "
                "directory holding your coinhsl-*.tar.gz (and optional hsl_ma*-*.tar.gz)")
    if not args.sources.is_dir():
        die(f"--sources {args.sources} is not a directory")

    flavor_name = args.flavor or active_flavor()
    flavor = load_flavor(flavor_name, REPO / 'flavors')
    stack = Path(flavor['prefix'])
    is_macos = flavor.get('platform', 'linux') == 'macos'
    host_macos = platform.system() == 'Darwin'
    if is_macos != host_macos:
        die(f"flavor {flavor_name} is for {'macOS' if is_macos else 'Linux'}, "
            f"but this host is {platform.system()}")

    if args.install_stack and args.prefix:
        die("--install-stack and --prefix are exclusive")
    prefix = (stack if args.install_stack
              else (args.prefix or Path.home() / '.local' / 'scls-hsl' / flavor_name)).resolve()
    if args.work_dir:
        work = args.work_dir.resolve()
        if work.exists():
            die(f"--work-dir {work} already exists; give a path this run may create (it will be "
                f"removed afterwards unless --keep-work)")
    else:
        work = None   # created below, after the path checks
    # Never let HSL source or HSL-derived binaries land in the work tree (tmp/ is
    # git-ignored, but an ignore rule is one `git add -f` away from a leak), and
    # never into the stack prefix, where flavor-wide scans and packaging look.
    for label, p in (('--work-dir', work), ('--prefix', prefix)):
        if p is not None and is_within(p, REPO):
            die(f"{label} {p} is inside the SCLS work tree; HSL output must stay outside it")
    # HSL sources never go into the stack prefix. The built library may, but only
    # through the acceptance step below; the file will be unowned by any RPM/DEB.
    if work is not None and is_within(work, stack):
        die(f"--work-dir {work} is inside the stack prefix {stack}; HSL sources must stay out of it")
    if is_within(prefix, stack) and not args.install_stack:
        die(f"--prefix {prefix} is inside the stack prefix {stack}. Use `./scls install hsl` "
            f"(--install-stack), which shows the licence conditions and asks for acceptance")
    # A prefix outside the user's home is shared by construction (other users may
    # read it), so it takes the same acceptance step as the stack prefix.
    shared_install = args.install_stack or not is_within(prefix, Path.home())

    # Create the scratch dir now, after every check, and register it for removal.
    # It holds HSL source from the moment assembly starts.
    global CLEANUP_DIR
    if work is None:
        work = Path(tempfile.mkdtemp(prefix='scls-hsl-'))
    else:
        work.mkdir(parents=True, mode=0o700)
    if not args.keep_work:
        CLEANUP_DIR = work
    libmetis = stack / 'lib' / ('libmetis.dylib' if is_macos else 'libmetis.so')
    if not (stack / 'include' / 'metis.h').exists() or not libmetis.exists():
        die(f"stack METIS not found under {stack}; install scls-{flavor_name}-metis first")

    # The flavor names its compilers as bare commands and expects <stack>/bin
    # first on PATH, as unix_builder does (lbl/macos: the in-stack GCC). Intel
    # flavors additionally need oneAPI's setvars.sh sourced by the caller.
    env = dict(os.environ)
    env['PATH'] = f"{stack / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    cc = flavor['compilers']['cc']
    fc = flavor['compilers']['fc']
    for tool in (cc, fc):
        if not shutil.which(tool, path=env['PATH']):
            die(f"compiler {tool!r} for flavor {flavor_name} not found on PATH "
                f"(looked in {stack / 'bin'} first); for the intel flavor source oneAPI's "
                f"setvars.sh first")
    global RUN_ENV
    RUN_ENV = env
    family = compiler_family(flavor)
    omp = openmp_flag(flavor)
    flags = flavor.get('flags', {})
    mklroot = os.environ.get('MKLROOT', '/opt/intel/oneapi/mkl/latest')

    def expand(s: str) -> str:
        return s.replace('%{prefix}', str(stack)).replace('%{mklroot}', mklroot)

    cflags = shlex.split(expand(flags.get('cflags', '')))
    fflags = shlex.split(expand(flags.get('fflags', '')))
    # Flavor link flags (e.g. macOS -Wl,-headerpad_max_install_names), minus
    # -L/-rpath entries, which CMake sets from the stack and math line itself.
    ldextra = [t for t in shlex.split(expand(flags.get('ldflags', '')))
               if not t.startswith(('-L', '-Wl,-rpath'))]
    # gcc/mkl flavors carry no -O of their own (recipes add O_level); debug does.
    if not any(f.startswith('-O') for f in fflags):
        cflags.append('-O2')
        fflags.append('-O2')
    fextra = []
    # Same switch Coin-HSL's meson.build adds for gfortran >= 10: the F77 HSL
    # routines pass arrays of different types through the same dummy argument.
    if family == 'gnu' and gfortran_major(fc) >= 10:
        fextra.append('-fallow-argument-mismatch')

    # The flavor's BLAS/LAPACK line, built exactly as recipes with features.math get it.
    math_line = shlex.split(expand(get_math_link_line(
        flavor, {'features': {'math': 'serial', 'openmp': True, 'fortran': True}})))
    rpath = [str(stack / 'lib')]
    for tok in math_line:
        if tok.startswith('-Wl,-rpath,'):
            for d in tok[len('-Wl,-rpath,'):].split(','):
                if d and d not in rpath:
                    rpath.append(d)
    math_libs = [t for t in math_line if not t.startswith('-Wl,-rpath,')]

    cmake = stack / 'bin' / 'cmake'
    cmake = str(cmake) if cmake.exists() else shutil.which('cmake')
    if not cmake:
        die("no cmake found (stack or PATH)")

    print(f"flavor    : {flavor_name} (stack prefix {stack})")
    print(f"work dir  : {work}  (contains HSL sources; "
          f"{'kept (--keep-work)' if args.keep_work else 'removed on exit, success or failure'})")
    print(f"prefix    : {prefix}")

    # --- 1. assemble ----------------------------------------------------------
    assembled = work / 'assembled'
    if assembled.exists():
        die(f"{assembled} exists; use an empty --work-dir")
    run([HSL_DIR / 'assemble_sources.sh', *(['--no-overrides'] if args.no_overrides else []),
         args.sources.resolve(), assembled])
    src = assembled / 'src'
    provenance = (assembled / 'PROVENANCE.txt').read_text()

    files = manifest(src)
    sources_cmake = work / 'sources.cmake'
    sources_cmake.write_text('set(HSL_SOURCES\n' +
                             ''.join(f'  {cmake_quote(str(f))}\n' for f in files) + ')\n')
    # Every replaced file must be the one in the tree, and in the build.
    built = {str(f) for f in files}
    for rel, new_sha in re.findall(r"replaced: (\S+) coinhsl_sha256=\S+ new_sha256=(\S+)", provenance):
        p = src / rel
        sha = run(['sha256sum', p] if not host_macos else ['shasum', '-a', '256', p],
                  capture=True).split()[0]
        if sha != new_sha or str(p) not in built:
            die(f"override {rel} is not what will be compiled")

    # --- 2. configure, build, install to staging ---------------------------------
    build = work / 'build'
    stage = work / 'stage'
    run([cmake, '-S', HSL_DIR, '-B', build, '-G', 'Unix Makefiles',
         f'-DCMAKE_C_COMPILER={cc}', f'-DCMAKE_Fortran_COMPILER={fc}',
         f'-DCMAKE_C_FLAGS={shlex.join(cflags)}', f'-DCMAKE_Fortran_FLAGS={shlex.join(fflags)}',
         f'-DCMAKE_INSTALL_PREFIX={stage}',
         f'-DHSL_SOURCES_CMAKE={sources_cmake}',
         f'-DSCLS_STACK_PREFIX={stack}',
         f'-DHSL_MATH_LIBS={";".join(math_libs)}',
         *([f'-DHSL_FORTRAN_EXTRA_FLAGS={";".join(fextra)}'] if fextra else []),
         *([f'-DHSL_EXTRA_LINK_FLAGS={";".join(ldextra)}'] if ldextra else []),
         f'-DHSL_OPENMP_FLAG={omp}',
         f'-DHSL_INSTALL_RPATH={";".join(rpath)}',
         *([f'-DHSL_INSTALL_NAME_DIR={prefix / "lib"}'] if is_macos else [])])
    run([cmake, '--build', build, '-j', str(max(1, args.jobs))])
    run([cmake, '--install', build, '--prefix', stage])

    libname = 'libcoinhsl.dylib' if is_macos else 'libcoinhsl.so'
    staged = stage / 'lib' / libname
    if not staged.exists():
        die(f"cmake --install produced no {staged}")

    # --- 3. self-check on the staged library -------------------------------------
    nm = run(['nm', '-gU', staged] if is_macos else ['nm', '-D', '--defined-only', staged],
             capture=True)
    defined = {line.split()[-1].lstrip('_') if is_macos else line.split()[-1]
               for line in nm.splitlines() if line.strip()}
    missing = [s for s in IPOPT_SYMBOLS if s not in defined]
    if missing:
        die(f"library lacks symbols Ipopt loads: {missing}")
    leaked = sorted(s for s in defined if s.startswith(('METIS_', 'libmetis__', 'gk_')))
    if leaked:
        die(f"library defines METIS symbols itself (must use the stack's): {leaked[:5]}")

    needed = resolved_needed(staged, is_macos)
    unresolved = [n for n, p in needed.items() if not p]
    if unresolved:
        die(f"unresolved libraries: {unresolved}")
    linalg = flavor.get('math', {}).get('linalg')
    expect = {'libmetis': stack / 'lib'}
    if linalg == 'openblas':
        expect['libopenblas'] = stack / 'lib'
    elif linalg == 'lapack':
        expect.update({'libblas': stack / 'lib', 'liblapack': stack / 'lib'})
    elif linalg == 'mkl':
        expect.update({'libmkl_core': Path(mklroot), 'libmkl_': Path(mklroot)})
    for stem, root in expect.items():
        hits = {n: p for n, p in needed.items() if n.startswith(stem)}
        if not hits:
            die(f"{stem}* is not in the library's dependencies")
        for n, p in hits.items():
            if not is_within(Path(p), root):
                die(f"{n} resolves to {p}, expected under {root}")

    tests = work / 'tests'
    tests.mkdir()
    smoke_c = tests / 'smoke.c'
    smoke_c.write_text(
        '#include <dlfcn.h>\n#include <stdio.h>\n'
        'int main(int argc, char **argv) {\n'
        '  void *h = dlopen(argv[1], RTLD_NOW);\n'
        '  if (!h) { fprintf(stderr, "%s\\n", dlerror()); return 1; }\n'
        '  void (*a)(void *) = (void (*)(void *))dlsym(h, "ma97_default_control_d");\n'
        '  void (*b)(void *) = (void (*)(void *))dlsym(h, "mc68_default_control_i");\n'
        '  if (!a || !b) { fprintf(stderr, "symbol lookup failed\\n"); return 1; }\n'
        '  static double buf[1024];\n'
        '  a(buf); b(buf);\n'
        '  puts("smoke: dlopen + ma97/mc68 default_control OK");\n'
        '  return 0;\n}\n')
    run([cc, smoke_c, '-o', tests / 'smoke'] + ([] if is_macos else ['-ldl']))
    run([tests / 'smoke', staged])

    ma77 = tests / 'ma77_factor_solve'
    # Must test the STAGED library, never a copy already published in --prefix.
    # Linux: DT_NEEDED is the bare SONAME and this rpath resolves it to staging.
    # macOS: the dylib's id is the hard FINAL path (SCLS convention, no @rpath),
    # so the test executable's load command is rewritten to the staged file and
    # the binary re-signed ad hoc, as the stack's install-name normalizer does.
    run([cc, '-O2', f'-I{src / "hsl_ma77" / "C"}', HSL_DIR / 'tests' / 'ma77_factor_solve.c',
         '-o', ma77, f'-L{staged.parent}', '-lcoinhsl', f'-Wl,-rpath,{staged.parent}', '-lm'])
    if is_macos:
        run(['install_name_tool', '-change', prefix / 'lib' / libname, staged, ma77])
        run(['codesign', '-s', '-', '-f', ma77])
        loads = run(['otool', '-L', ma77], capture=True)
        if str(staged) not in loads:
            die("MA77 test executable does not reference the staged library after install_name_tool")
    ma77_dir = tests / 'ma77-files'
    ma77_dir.mkdir()
    # Test 1 always. Test 2 (refactorization after a failed factorization) needs
    # HSL_MA77 >= 6.5.0, i.e. the standalone override; Coin-HSL's own copy is
    # expected to fail it, so it is skipped for a base-only build.
    # Applied overrides are recorded as "override: <pkg> <old> -> <new> ..."; skipped
    # ones as "override: <pkg> skipped ...". Only the former counts.
    ma77_overridden = bool(re.search(r"^override: HSL_MA77 [0-9][^\n]* -> ", provenance, re.M))
    run([ma77, ma77_dir, 'full' if ma77_overridden else 'basic'])
    if not ma77_overridden:
        print("note: MA77 refactorization test skipped (needs HSL_MA77 >= 6.5.0; Coin-HSL base only)")

    if linalg == 'mkl':
        run([REPO / 'scripts' / 'check_mkl_linkage.sh', '--flavor', flavor_name, '--prefix', stage])

    # --- 3b. licence acceptance for a stack-prefix install ------------------------------
    acceptance = {}
    if shared_install:
        where = str(stack) if args.install_stack else str(prefix)
        lic_files = sorted((assembled / 'LICENCES').iterdir())
        print("\n" + "=" * 78)
        print("INSTALLING INTO A SHARED LOCATION: " + where)
        print("The library will be readable by every user of that location and is owned by no package.")
        print("These are the licence files shipped in the HSL tarballs you supplied:\n")
        for lic in lic_files:
            print(f"----- {lic.name} -----")
            print(lic.read_text(errors='replace').rstrip())
            print()
        print("=" * 78)
        print("Note: Coin-HSL's own LICENCE is a pointer to the agreement you accepted on the STFC")
        print("portal; the terms are in that agreement, not in the tarball. Under the HSL ACADEMIC")
        print("licence (version 2.0), use is personal to you: it may not be shared with anyone,")
        print("including colleagues at your own institution, and may not be used commercially.")
        print("An academic licence therefore does NOT permit this shared install on a machine used")
        print("by others. It is permitted only if nobody else can use this location, or if you hold a")
        print("licence whose terms allow it. SCLS distributes nothing and grants no rights.")
        print("By accepting you confirm that you have read your HSL licence agreement and that it")
        print("covers use of this library here by everyone who can use " + where + ".")
        if args.accept_licence:
            print("Accepted via --accept-licence.")
            how = '--accept-licence'
        elif sys.stdin.isatty():
            answer = input("Type 'yes' to accept and install, anything else to abort: ").strip()
            if answer != 'yes':
                die("licence not accepted; nothing installed")
            how = 'interactive'
        else:
            die("a shared install needs licence acceptance: run on a terminal or pass --accept-licence")
        acceptance = {
            'accepted_by': os.environ.get('USER') or str(os.getuid()),
            'uid': os.getuid(), 'host': socket.gethostname(), 'how': how,
            'when': datetime.now().astimezone().isoformat(timespec='seconds'),
            'licence_texts_sha256': {l.name: hashlib.sha256(l.read_bytes()).hexdigest() for l in lic_files},
        }

    # --- 4. publish ------------------------------------------------------------------
    libdir = prefix / 'lib'
    docdir = prefix / 'share' / 'doc' / 'hsl'
    infodir = prefix / 'share' / 'hsl'
    # Publish into a second staging tree with the final layout, then copy it over
    # in one step: plain copy for a writable prefix, `sudo install` otherwise
    # (the stack prefix is root-owned; the build itself never runs as root).
    pub = work / 'publish'
    (pub / 'lib').mkdir(parents=True)
    (pub / 'share' / 'doc' / 'hsl').mkdir(parents=True)
    (pub / 'share' / 'hsl').mkdir(parents=True)
    shutil.copy2(staged, pub / 'lib' / libname)
    alias_name = 'libhsl.dylib' if is_macos else 'libhsl.so'   # Ipopt's default hsllib name
    shutil.copytree(assembled / 'LICENCES', pub / 'share' / 'doc' / 'hsl' / 'LICENCES')
    shutil.copy2(assembled / 'PROVENANCE.txt', pub / 'share' / 'doc' / 'hsl' / 'PROVENANCE.txt')
    alias = libdir / alias_name

    def publish_tree(src_root: Path, dst_root: Path) -> None:
        # A personal prefix is owner-only (dirs 0700, files 0600): "personal use"
        # must not become sharing through a traversable home directory. A shared
        # install (accepted above) is world-readable. `install -d` + `install -m`
        # rather than GNU-only `install -D`, so the same code runs on macOS.
        dmode, fmode = ('0755', '0644') if shared_install else ('0700', '0600')
        parent = dst_root
        while not parent.exists():
            parent = parent.parent
        writable = os.access(parent, os.W_OK)
        sudo = [] if writable else ['sudo']
        if not writable:
            print(f"{dst_root} is not writable; publishing with sudo (files only)")
        # Every directory from the prefix root down gets dmode, so a personal
        # prefix is closed at its root, not only at the leaves holding files.
        dirs = {Path('.')}
        for f in src_root.rglob('*'):
            if f.is_file():
                rel = f.parent.relative_to(src_root)
                dirs.update([rel, *rel.parents])
        for d in sorted(dirs, key=lambda x: len(x.parts)):
            run([*sudo, 'install', '-d', '-m', dmode, dst_root / d])
        for f in sorted(p for p in src_root.rglob('*') if p.is_file()):
            run([*sudo, 'install', '-m', fmode, f, dst_root / f.relative_to(src_root)])
        run([*sudo, 'ln', '-sfn', libname, dst_root / 'lib' / alias_name])

    cmake_version = run([cmake, '--version'], capture=True).splitlines()[0]
    (pub / 'share' / 'hsl' / 'build-info.yaml').write_text(
        f"built: {datetime.now().isoformat(timespec='seconds')}\n"
        f"flavor: {flavor_name}\n"
        f"stack_prefix: {stack}\n"
        f"overrides: {'disabled' if args.no_overrides else 'enabled'}\n"
        f"scripts:\n"
        f"  build_libhsl.py: {git_blob(Path(__file__))}\n"
        f"  assemble_sources.sh: {git_blob(HSL_DIR / 'assemble_sources.sh')}\n"
        f"  CMakeLists.txt: {git_blob(HSL_DIR / 'CMakeLists.txt')}\n"
        f"  ma77_factor_solve.c: {git_blob(HSL_DIR / 'tests' / 'ma77_factor_solve.c')}\n"
        f"cmake: {cmake} ({cmake_version})\n"
        f"cc: {cc}\n"
        f"fc: {fc} ({run([fc, '-dumpversion'], capture=True).strip()})\n"
        f"cflags: {json.dumps(shlex.join(cflags))}\n"
        f"fflags: {json.dumps(shlex.join(fflags + [omp] + fextra))}\n"
        f"math_libs: {json.dumps(shlex.join(math_libs))}\n"
        f"rpath: {json.dumps(':'.join(rpath))}\n"
        f"install_mode: {'stack' if args.install_stack else ('shared' if shared_install else 'personal')}\n"
        f"needed:\n" + ''.join(f"  {n}: {p}\n" for n, p in needed.items()) +
        (("licence_acceptance:\n" + ''.join(
            f"  {k}: {json.dumps(v)}\n" for k, v in acceptance.items())) if acceptance else ''))
    publish_tree(pub, prefix)

    cleanup()

    print(f"\nInstalled {libdir / libname} (+ {alias.name} symlink)")
    print(f"Licences and provenance: {docdir}")
    if args.install_stack:
        print("Ipopt finds it through libipopt's RUNPATH; no hsllib option is needed. In ipopt.opt:")
        print("  linear_solver ma97")
        print("Installed for every user of this prefix on the licence you confirmed; the acceptance is")
        print("recorded in share/hsl/build-info.yaml.")
    else:
        print("Use it from Ipopt by giving the full path, in ipopt.opt or via AddIpoptStrOption:")
        print(f"  hsllib {alias}")
        print("  linear_solver ma97")
        print("(SCLS never uses LD_LIBRARY_PATH / DYLD_LIBRARY_PATH. For Ipopt to find it with no")
        print(" option, `./scls install hsl` installs into the stack prefix after licence acceptance.)")
        if not shared_install:
            print("Installed owner-only (0700/0600): under the HSL Academic Licence the library is for your")
            print("personal use and may not be shared, including within your institution.")


if __name__ == '__main__':
    main()
