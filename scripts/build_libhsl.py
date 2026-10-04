#!/usr/bin/env python3
"""Build a private libhsl for Ipopt's runtime loader from a licensee's own HSL tarballs.

HSL is proprietary (STFC HSL licence). SCLS never ships, stages, or commits HSL
source or anything built from it; only these scripts are public. A licensee runs
this against the original tarballs they obtained themselves:

    ./scls build hsl      assemble, build, check; stage under $TMPDIR/scls-hsl-<uid>/<flavor>
    ./scls install hsl    ask install type (local|global), licence type (academic|commercial)
                          and acceptance; publish; remove the staged build

and gets a shared library that the stack's unchanged libipopt can dlopen
(`linear_solver ma97`; local installs add `hsllib <full path>` to ipopt.opt).

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


def build_cache_dir(flavor_name: str) -> Path:
    """Where `build` leaves the checked, staged result for `install`.

    Deterministic, owner-only, under the system temp dir ($TMPDIR or /tmp), so
    nothing HSL-derived persists anywhere but the final install location:
    `install` deletes it once the install succeeded, and a reboot clears it.
    """
    return Path(tempfile.gettempdir()) / f"scls-hsl-{os.getuid()}" / flavor_name


def macos_dylib_id(lib: Path) -> str:
    out = [l.strip() for l in run(['otool', '-D', lib], capture=True).splitlines() if l.strip()]
    return out[-1] if len(out) > 1 else ''   # first line is the file name


def set_macos_dylib_id(lib: Path, new_id: Path) -> None:
    """Give `lib` the install name `new_id`, ad-hoc signed; a no-op if it has it.

    Works on a copy and renames it over `lib` only once the id and the signature
    verify, so `lib` is never left half-rewritten for a later install attempt.
    """
    if macos_dylib_id(lib) == str(new_id):
        return
    tmp = lib.with_name(lib.name + '.newid')
    shutil.copy2(lib, tmp)
    os.chmod(tmp, 0o600)
    try:
        run(['install_name_tool', '-id', new_id, tmp])
        run(['codesign', '-s', '-', '-f', tmp])
        run(['codesign', '-v', tmp])
        if macos_dylib_id(tmp) != str(new_id):
            die(f"{lib}: install name is not {new_id} after install_name_tool")
        os.chmod(tmp, 0o600)
        os.replace(tmp, lib)
    finally:
        tmp.unlink(missing_ok=True)


def common_flavor(args):
    flavor_name = args.flavor or active_flavor()
    flavor = load_flavor(flavor_name, REPO / 'flavors')
    stack = Path(flavor['prefix'])
    is_macos = flavor.get('platform', 'linux') == 'macos'
    if is_macos != (platform.system() == 'Darwin'):
        die(f"flavor {flavor_name} is for {'macOS' if is_macos else 'Linux'}, "
            f"but this host is {platform.system()}")
    return flavor_name, flavor, stack, is_macos


def cmd_build(args) -> None:
    if args.sources is None:
        # tmp/ is git-ignored; it is where a licensee drops the tarballs by hand.
        if (REPO / 'tmp' / 'HSL').is_dir():
            args.sources = REPO / 'tmp' / 'HSL'
        else:
            die("no --sources given and tmp/HSL does not exist; point --sources at the "
                "directory holding your coinhsl-*.tar.gz (and optional hsl_ma*-*.tar.gz)")
    if not args.sources.is_dir():
        die(f"--sources {args.sources} is not a directory")

    flavor_name, flavor, stack, is_macos = common_flavor(args)
    host_macos = is_macos

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
    if work is not None and is_within(work, REPO):
        die(f"--work-dir {work} is inside the SCLS work tree; HSL output must stay outside it")
    # HSL sources never go into the stack prefix (packaging and flavor-wide scans look there).
    if work is not None and is_within(work, stack):
        die(f"--work-dir {work} is inside the stack prefix {stack}; HSL sources must stay out of it")

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
    print(f"build dir : {build_cache_dir(flavor_name)}  (staged result for `./scls install hsl`)")

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
         *([f'-DHSL_INSTALL_NAME_DIR={stack / "lib"}'] if is_macos else [])])
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
    # macOS: the dylib's id is the hard path under the stack prefix (SCLS
    # convention, no @rpath; final for a global install, rewritten by `install`
    # for a local one), so the test executable's load command is rewritten to the
    # staged file and the binary re-signed ad hoc, as the stack's install-name
    # normalizer does.
    run([cc, '-O2', f'-I{src / "hsl_ma77" / "C"}', HSL_DIR / 'tests' / 'ma77_factor_solve.c',
         '-o', ma77, f'-L{staged.parent}', '-lcoinhsl', f'-Wl,-rpath,{staged.parent}', '-lm'])
    if is_macos:
        run(['install_name_tool', '-change', stack / 'lib' / libname, staged, ma77])
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


    # --- 4. stage the checked result for `install` -----------------------------------
    cache = build_cache_dir(flavor_name)
    if cache.exists():
        shutil.rmtree(cache)
    cache.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(cache.parent, 0o700)
    cache.mkdir(mode=0o700)
    (cache / 'lib').mkdir(mode=0o700)
    (cache / 'share' / 'doc' / 'hsl').mkdir(parents=True, mode=0o700)
    (cache / 'share' / 'hsl').mkdir(parents=True, mode=0o700)
    shutil.copy2(staged, cache / 'lib' / libname)
    shutil.copytree(assembled / 'LICENCES', cache / 'share' / 'doc' / 'hsl' / 'LICENCES')
    shutil.copy2(assembled / 'PROVENANCE.txt', cache / 'share' / 'doc' / 'hsl' / 'PROVENANCE.txt')
    cmake_version = run([cmake, '--version'], capture=True).splitlines()[0]
    (cache / 'share' / 'hsl' / 'build-info.yaml').write_text(
        f"built: {datetime.now().astimezone().isoformat(timespec='seconds')}\n"
        f"flavor: {flavor_name}\n"
        f"stack_prefix: {stack}\n"
        f"library: {libname}\n"
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
        f"needed:\n" + ''.join(f"  {n}: {p}\n" for n, p in needed.items()))
    for f in cache.rglob('*'):
        os.chmod(f, 0o700 if f.is_dir() else 0o600)
    cleanup()
    print(f"\nBuilt and checked: {cache / 'lib' / libname}")
    print("Not installed yet. Install with:  ./scls install hsl")
    print("(asks for install type, licence type and acceptance; the build dir is removed afterwards)")


def ask_choice(prompt: str, choices: list, flag_value, flag_names: str) -> str:
    if flag_value:
        return flag_value
    if not sys.stdin.isatty():
        die(f"{prompt}: no terminal; pass {flag_names}")
    while True:
        a = input(f"{prompt} [{'/'.join(choices)}]: ").strip().lower()
        if a in choices:
            return a
        print(f"  please answer one of: {', '.join(choices)}")


# Stack package that provides a library libcoinhsl needs, by file-name stem.
NEEDED_PROVIDERS = (
    ('libmetis', 'metis'), ('libopenblas', 'openblas'),
    ('libblas', 'lapack'), ('liblapack', 'lapack'),
    ('libgomp', 'gcc'), ('libgfortran', 'gcc'), ('libgcc_s', 'gcc'), ('libquadmath', 'gcc'),
)


def registry_entry(cache: Path, info: str, stack: Path) -> str:
    """Registry YAML for a global install (same keys as build_common.write_registry_entry).

    Hand-written on purpose: write_registry_entry would see libhsl in lib/ and record
    -L/-rpath link flags. cflags/ldflags stay empty so nothing links HSL through the
    registry. dependencies lists the stack packages the library resolves against (from
    the `needed:` record), so `unix_builder.py --uninstall` of one of them refuses while
    HSL is installed. An external MKL has no stack package and is not listed.
    """
    doc = cache / 'share' / 'doc' / 'hsl'
    version = 'unknown'
    m = re.search(r"^base:\s+coinhsl-(\S+)", (doc / 'PROVENANCE.txt').read_text(), re.M) \
        if (doc / 'PROVENANCE.txt').exists() else None
    if m:
        version = m.group(1)
    else:
        for lic in sorted((doc / 'LICENCES').glob('LICENCE.coinhsl-*')):
            version = lic.name[len('LICENCE.coinhsl-'):]
    deps = []
    needed = info.split('\nneeded:\n', 1)[-1].split('\nlicence_acceptance:\n')[0]
    for name, path in re.findall(r"^  (\S+): (\S+)$", needed, re.M):
        if not is_within(Path(path), stack):
            continue
        for stem, pkg in NEEDED_PROVIDERS:
            if (name.startswith(stem) and pkg not in deps
                    and (stack / 'share' / 'scls' / 'registry' / f'{pkg}.yaml').exists()):
                deps.append(pkg)
    return (
        "name: hsl\n"
        f"version: {json.dumps(version)}\n"
        "license: Proprietary (STFC HSL licence); licensee-built, not redistributable\n"
        "summary: HSL linear solvers for Ipopt, private build loaded at runtime (hsllib)\n"
        "dependencies:\n" + ''.join(f"- {d}\n" for d in deps) +
        "cflags: ''\n"
        "ldflags: ''\n"
        "features:\n  fortran: true\n  openmp: true\n  mpi: false\n  math: true\n"
        "has_pc_file: false\n"
    )


def cmd_install(args) -> None:
    flavor_name, flavor, stack, is_macos = common_flavor(args)
    cache = build_cache_dir(flavor_name)
    info_file = cache / 'share' / 'hsl' / 'build-info.yaml'
    if not info_file.exists():
        die(f"no build found for flavor {flavor_name} ({cache}); run `./scls build hsl` first")
    info = info_file.read_text()
    m = re.search(r"^library: (\S+)$", info, re.M)
    libname = m.group(1) if m else ('libcoinhsl.dylib' if is_macos else 'libcoinhsl.so')
    alias_name = 'libhsl.dylib' if is_macos else 'libhsl.so'   # Ipopt's default hsllib name
    if not (cache / 'lib' / libname).exists():
        die(f"build dir {cache} is incomplete; run `./scls build hsl` again")
    lic_files = sorted((cache / 'share' / 'doc' / 'hsl' / 'LICENCES').iterdir())

    # --- 1. install type -------------------------------------------------------------
    print("Install type:")
    print("  local   ~/.local/scls-hsl/<flavor>, owner-only (0700/0600). Ipopt needs")
    print("          `hsllib <full path>` in ipopt.opt or via the API.")
    print(f"  global  the stack prefix {stack}, readable by every user of this machine,")
    print("          owned by no RPM/DEB package, installed with sudo. Ipopt finds it with no option.")
    flag = 'local' if args.local else ('global' if args.glob else None)
    itype = ask_choice("Install type", ['local', 'global'], flag, '--local or --global')
    prefix = stack if itype == 'global' else Path.home() / '.local' / 'scls-hsl' / flavor_name
    if itype == 'local' and is_within(prefix, REPO):
        die(f"{prefix} is inside the SCLS work tree")

    # --- 2. licence type -------------------------------------------------------------
    print("\nLicence type:")
    print("  academic    HSL Academic Licence: personal, non-commercial use by you alone; the")
    print("              software and its use may not be shared with anyone, including colleagues")
    print("              at your own institution.")
    print("  commercial  a commercial / site agreement with STFC whose terms you hold.")
    ltype = ask_choice("Licence type", ['academic', 'commercial'], args.licence,
                       '--licence academic|commercial')
    single_user = None
    if itype == 'global' and ltype == 'academic':
        print("\nAn academic licence does NOT permit a global install on a machine that other people")
        print("use: every user of " + str(stack) + " could run the library, which the licence forbids.")
        print("It is permissible only if you are the sole user of this machine.")
        ans = ask_choice("Are you the sole user of this machine", ['yes', 'no'],
                         'yes' if args.sole_user else None, '--sole-user')
        if ans != 'yes':
            die("global install not permitted under an academic licence on a shared machine; "
                "choose a local install")
        single_user = True

    # --- 3. acceptance ---------------------------------------------------------------
    print("\n" + "=" * 78)
    print("These are the licence files shipped in the HSL tarballs you supplied:\n")
    for lic in lic_files:
        print(f"----- {lic.name} -----")
        print(lic.read_text(errors='replace').rstrip())
        print()
    print("=" * 78)
    print("Note: Coin-HSL's own LICENCE is a pointer to the agreement you accepted on the STFC")
    print("portal; the terms are in that agreement. SCLS distributes nothing and grants no rights.")
    if ltype == 'academic':
        print("By accepting you confirm that you hold an HSL Academic Licence for every package you")
        print("supplied, that you have read it, and that this install is for your personal,")
        print("non-commercial use" + (" on a machine only you use." if itype == 'global' else "."))
    else:
        print("By accepting you confirm that you have read your commercial/site agreement with STFC")
        print(f"and that it covers use of this library at {prefix} by everyone who can use it.")
    if args.accept_licence:
        how = '--accept-licence'
        print("Accepted via --accept-licence.")
    elif sys.stdin.isatty():
        if input("Type 'yes' to accept and install, anything else to abort: ").strip() != 'yes':
            die("licence not accepted; nothing installed")
        how = 'interactive'
    else:
        die("acceptance needs a terminal or --accept-licence")
    acceptance = {
        'install_type': itype, 'licence_type': ltype,
        **({'sole_user_confirmed': True} if single_user else {}),
        'accepted_by': os.environ.get('USER') or str(os.getuid()),
        'uid': os.getuid(), 'host': socket.gethostname(), 'how': how,
        'when': datetime.now().astimezone().isoformat(timespec='seconds'),
        'licence_texts_sha256': {l.name: hashlib.sha256(l.read_bytes()).hexdigest() for l in lic_files},
    }

    # --- 4. publish ------------------------------------------------------------------
    # Local: owner-only, so personal use cannot become sharing through a traversable
    # home. Global: world-readable, sudo for the root-owned prefix (only the file
    # copies run as root). `install -d/-m` rather than GNU-only `install -D` (macOS).
    dmode, fmode = ('0755', '0644') if itype == 'global' else ('0700', '0600')
    # macOS: the build linked in the id <stack>/lib/<libname>, which is already
    # right for a global install (published byte-identical to what was checked).
    # A local install lives elsewhere, so the id is rewritten on the owner-only
    # build-dir copy, which needs no sudo. Keyed on the id, not the install type:
    # a global install after a failed local one sets it back.
    if is_macos:
        set_macos_dylib_id(cache / 'lib' / libname, prefix / 'lib' / libname)
    # Recorded only now, and replacing any record a failed earlier attempt left.
    info_file.write_text(info.split('\nlicence_acceptance:\n')[0].rstrip('\n') + "\nlicence_acceptance:\n" +
                         ''.join(f"  {k}: {json.dumps(v)}\n" for k, v in acceptance.items()))
    # Global install: a registry entry, so `./scls list` shows it and
    # `unix_builder.py --uninstall -p hsl` (file list: files/hsl.txt) removes it.
    # A local record of this install, not a package: still no recipe, spec or
    # build-order slot. Written before the directory walk below so the same loop
    # publishes it. A local install is outside the stack prefix and gets none.
    # The cache survives a failed attempt, so drop what an earlier global one left.
    shutil.rmtree(cache / 'share' / 'scls', ignore_errors=True)
    if itype == 'global':
        registry = cache / 'share' / 'scls' / 'registry'
        registry.mkdir(parents=True)
        (registry / 'hsl.yaml').write_text(registry_entry(cache, info, stack))
    parent = prefix
    while not parent.exists():
        parent = parent.parent
    sudo = [] if os.access(parent, os.W_OK) else ['sudo']
    if sudo:
        print(f"{prefix} is not writable; publishing with sudo (file copies only)")
    dirs = {Path('.')}
    for f in cache.rglob('*'):
        if f.is_file():
            rel = f.parent.relative_to(cache)
            dirs.update([rel, *rel.parents])
    for d in sorted(dirs, key=lambda x: len(x.parts)):
        run([*sudo, 'install', '-d', '-m', dmode, prefix / d])
    for f in sorted(p for p in cache.rglob('*') if p.is_file()):
        run([*sudo, 'install', '-m', fmode, f, prefix / f.relative_to(cache)])
    run([*sudo, 'ln', '-sfn', libname, prefix / 'lib' / alias_name])

    shutil.rmtree(cache)   # the build dir is gone once the install succeeded
    print(f"\nInstalled {prefix / 'lib' / libname} (+ {alias_name} symlink); build dir removed.")
    print(f"Licences, provenance and the acceptance record: {prefix / 'share'}")
    if itype == 'global':
        print("Listed by `./scls list` as hsl. To remove it, from the SCLS checkout:")
        print(f"  python python/unix_builder.py --uninstall -p hsl -f {flavor_name}")
        print("Ipopt finds it through libipopt's RUNPATH; no hsllib option is needed. In ipopt.opt:")
        print("  linear_solver ma97")
    else:
        print("Use it from Ipopt by giving the full path, in ipopt.opt or via AddIpoptStrOption:")
        print(f"  hsllib {prefix / 'lib' / alias_name}")
        print("  linear_solver ma97")
        print("(SCLS never uses LD_LIBRARY_PATH / DYLD_LIBRARY_PATH.)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--flavor', default=None, help='SCLS flavor (default: flavor.conf)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='assemble, build and check libhsl; stage it for install')
    b.add_argument('--sources', type=Path, default=None,
                   help='directory holding the original HSL tarballs (never downloaded); '
                        'default: tmp/HSL under the SCLS checkout if it exists')
    b.add_argument('--work-dir', type=Path, default=None,
                   help='scratch directory for sources and build (must not exist; default: new dir in $TMPDIR)')
    b.add_argument('--keep-work', action='store_true',
                   help='keep the scratch directory (it contains HSL sources: never share it)')
    b.add_argument('--no-overrides', action='store_true',
                   help='build Coin-HSL as shipped, without standalone overrides')
    b.add_argument('--jobs', type=int, default=os.cpu_count() or 1)
    i = sub.add_parser('install', help='install the staged build; asks install type, licence type, acceptance')
    for sp in (b, i):   # --flavor is accepted before or after the subcommand
        sp.add_argument('--flavor', default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    g = i.add_mutually_exclusive_group()
    g.add_argument('--local', action='store_true', help='install type: ~/.local/scls-hsl/<flavor>, owner-only')
    g.add_argument('--global', dest='glob', action='store_true', help='install type: the stack prefix, for all users')
    i.add_argument('--licence', choices=['academic', 'commercial'], default=None, help='licence type')
    i.add_argument('--sole-user', action='store_true',
                   help='with --global and --licence academic: confirm you are the sole user of this machine')
    i.add_argument('--accept-licence', action='store_true',
                   help='non-interactive acceptance: you confirm you have read your HSL licence agreement '
                        'and that the chosen install is within its terms')
    args = ap.parse_args()
    if args.cmd == 'build':
        cmd_build(args)
    else:
        cmd_install(args)


if __name__ == '__main__':
    main()
