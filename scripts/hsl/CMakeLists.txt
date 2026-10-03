# Build libcoinhsl from an assembled HSL source tree (SCLS, BSD-3-Clause-LBNL).
#
# SCLS code only; it names no HSL file. The source list arrives in a generated
# file (HSL_SOURCES_CMAKE) written by scripts/build_libhsl.py from the assembled
# tree, which scripts/hsl/assemble_sources.sh built from the licensee's own
# tarballs. Never point this at a directory inside the SCLS work tree.
#
# Inputs (all set by scripts/build_libhsl.py):
#   CMAKE_C_COMPILER, CMAKE_Fortran_COMPILER   the flavor's cc / fc
#   CMAKE_C_FLAGS, CMAKE_Fortran_FLAGS          the flavor's cflags / fflags
#   HSL_SOURCES_CMAKE        file that sets HSL_SOURCES (absolute paths)
#   HSL_INCLUDE_DIRS         extra include dirs (none needed for Coin-HSL)
#   SCLS_STACK_PREFIX        e.g. /opt/scls/gcc: METIS and math libraries
#   HSL_MATH_LIBS            the flavor's BLAS/LAPACK link line, as a ;-list
#   HSL_FORTRAN_EXTRA_FLAGS  e.g. -fallow-argument-mismatch (;-list)
#   HSL_OPENMP_FLAG          -fopenmp / -qopenmp
#   HSL_EXTRA_LINK_FLAGS     flavor ldflags minus -L/-rpath (;-list, optional)
#   HSL_INSTALL_RPATH        ;-list baked into the library (stack lib, MKL lib)
#   HSL_INSTALL_NAME_DIR     macOS only: <final prefix>/lib (hard path, never @rpath)
#
# Deliberately not used:
#   CMAKE_BUILD_TYPE flags   only the flavor's flags apply (no extra -O3/-DNDEBUG)
#   FindBLAS / FindLAPACK    could pick another MKL threading layer or a system
#                            BLAS; the flavor's line is validated by math_common
#   build_common.get_cmake_args  sets C/CXX standard libraries only and leaves
#                            --no-as-needed off by default; see review_libhsl_plan

cmake_minimum_required(VERSION 3.20)
project(scls_coinhsl LANGUAGES C Fortran)

set(CMAKE_BUILD_TYPE "" CACHE STRING "" FORCE)

foreach(var HSL_SOURCES_CMAKE SCLS_STACK_PREFIX HSL_OPENMP_FLAG)
  if(NOT DEFINED ${var} OR "${${var}}" STREQUAL "")
    message(FATAL_ERROR "${var} must be set (run scripts/build_libhsl.py)")
  endif()
endforeach()

include("${HSL_SOURCES_CMAKE}")
if(NOT HSL_SOURCES)
  message(FATAL_ERROR "${HSL_SOURCES_CMAKE} defined no HSL_SOURCES")
endif()

# One METIS: the stack's, by full path, never a default search path.
find_library(HSL_METIS_LIBRARY NAMES metis PATHS "${SCLS_STACK_PREFIX}/lib"
             NO_DEFAULT_PATH REQUIRED)
find_path(HSL_METIS_INCLUDE_DIR metis.h PATHS "${SCLS_STACK_PREFIX}/include"
          NO_DEFAULT_PATH REQUIRED)

add_library(coinhsl SHARED ${HSL_SOURCES})
set_target_properties(coinhsl PROPERTIES
  LINKER_LANGUAGE Fortran
  POSITION_INDEPENDENT_CODE ON
  Fortran_MODULE_DIRECTORY "${CMAKE_BINARY_DIR}/modules"
  # No VERSION/SOVERSION: the file and its SONAME are both libcoinhsl.so, as
  # upstream's own build produces. Ipopt dlopens it by name, so no consumer
  # records the SONAME in DT_NEEDED.
  # The final RPATH / install name is linked in directly. cmake --install then
  # has no RPATH to rewrite, and the staged copy that build_libhsl.py checks is
  # byte-identical to the one it installs.
  BUILD_WITH_INSTALL_RPATH ON
  INSTALL_RPATH "${HSL_INSTALL_RPATH}"
  INSTALL_RPATH_USE_LINK_PATH OFF)
if(APPLE)
  # Hard install name, the SCLS macOS convention (tools/fix_macos_install_names.sh
  # makes every stack id absolute; @rpath is not used anywhere in the stack). It
  # is linked in at build time so the staged copy is byte-identical to the one
  # published. The pre-publish MA77 test must therefore not trust this id, which
  # points at the FINAL location: build_libhsl.py rewrites the test executable's
  # load command to the staged file with install_name_tool -change.
  if(NOT HSL_INSTALL_NAME_DIR)
    message(FATAL_ERROR "HSL_INSTALL_NAME_DIR must be set on macOS")
  endif()
  set_target_properties(coinhsl PROPERTIES INSTALL_NAME_DIR "${HSL_INSTALL_NAME_DIR}"
                                           BUILD_WITH_INSTALL_NAME_DIR ON)
endif()

# metis5_adapter.c includes "metis.h"; no such file exists in the Coin-HSL tree,
# so the stack's header (IDXTYPEWIDTH 32) is the one it compiles against.
target_include_directories(coinhsl PRIVATE "${HSL_METIS_INCLUDE_DIR}" ${HSL_INCLUDE_DIRS})

# OpenMP on Fortran only, as Coin-HSL's own meson.build does; the C adapter has
# no OpenMP code. The flavor's flag, not find_package(OpenMP), so the runtime is
# the one the flavor's math line already names (libgomp / libiomp5).
target_compile_options(coinhsl PRIVATE "$<$<COMPILE_LANGUAGE:Fortran>:${HSL_OPENMP_FLAG}>")
if(HSL_FORTRAN_EXTRA_FLAGS)
  target_compile_options(coinhsl PRIVATE
    "$<$<COMPILE_LANGUAGE:Fortran>:${HSL_FORTRAN_EXTRA_FLAGS}>")
endif()

# SCLS link policy: --no-as-needed, so every library on the flavor line stays
# in DT_NEEDED (doc/MKL_ABI_POLICY.md, check_mkl_linkage.sh requires it).
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
  target_link_options(coinhsl PRIVATE "LINKER:--no-as-needed")
endif()
target_link_options(coinhsl PRIVATE "${HSL_OPENMP_FLAG}")
if(HSL_EXTRA_LINK_FLAGS)
  target_link_options(coinhsl PRIVATE ${HSL_EXTRA_LINK_FLAGS})
endif()
# The reference-BLAS flavor's math line is bare -llapack -lblas (no -L); the
# OpenBLAS and MKL lines carry their own. The stack lib dir covers the former.
target_link_directories(coinhsl PRIVATE "${SCLS_STACK_PREFIX}/lib")
target_link_libraries(coinhsl PRIVATE "${HSL_METIS_LIBRARY}" ${HSL_MATH_LIBS})

install(TARGETS coinhsl LIBRARY DESTINATION lib)
