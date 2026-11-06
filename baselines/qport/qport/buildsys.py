"""Detect the build system and Linux assumptions in build files."""
import os
import re

from . import kb
from .scan import Finding

BUILD_FILES = {
    "CMakeLists.txt": "cmake", "meson.build": "meson", "configure.ac": "autotools",
    "configure.in": "autotools", "Makefile.am": "autotools", "configure": "autotools",
    "Makefile": "make", "makefile": "make", "GNUmakefile": "make", "BUILD.bazel": "bazel",
    "SConstruct": "scons", "premake5.lua": "premake",
}

CMAKE_RULES = [
    (re.compile(r'CMAKE_SYSTEM_NAME\s+(STREQUAL|MATCHES)\s+"?Linux', re.I),
     "Branch taken only when CMAKE_SYSTEM_NAME is Linux. The QNX toolchain file sets it to QNX, "
     "so add a QNX case (or test for the feature instead of the OS)."),
    (re.compile(r'\bif\s*\(\s*(NOT\s+)?LINUX\b'),
     "The LINUX variable is false for QNX; check what this branch enables."),
    (re.compile(r'\bif\s*\(\s*UNIX\s+AND\s+NOT\s+APPLE'),
     "'UNIX AND NOT APPLE' is often used to mean Linux; QNX also matches UNIX, so the Linux "
     "branch will be taken on QNX."),
    (re.compile(r'pkg_check_modules\s*\([^)]*\b(libsystemd|libudev|libseccomp|libcap)\b', re.I),
     "Depends on a Linux-only library; make it optional for QNX."),
    (re.compile(r'(target_link_libraries|set\s*\(\s*\w*LIB\w*)[^)\n]*\bpthread\b(?!s)', re.I),
     "Links libpthread explicitly. QNX has the pthread API in libc and no separate libpthread; "
     "use find_package(Threads) / Threads::Threads, or skip it on QNX as the QNX libwebsockets port "
     "does. Evidence: " + kb.PTHREAD_LIB_EVIDENCE),
    (re.compile(r'(check_symbol_exists|check_function_exists|CHECK_SYMBOLS_EXIST|check_cxx_symbol_exists)'
                r'\s*\(\s*\$?\{?(socket|getaddrinfo|inet_ntop|inet_pton|getnameinfo|accept4|setsockopt|'
                r'SYMLIST|getifaddrs|gethostbyname)', re.I),
     "Feature check for a socket function: on QNX it fails unless libsocket is linked during the "
     "check (set CMAKE_REQUIRED_LIBRARIES socket when QNX), as the QNX libevent port does. "
     "Evidence: " + kb.CMAKE_SOCKET_CHECK_EVIDENCE),
]
AUTOTOOLS_RULES = [
    (re.compile(r'\*-?linux\*|\*linux-gnu\*'),
     "Host case pattern matches Linux only; add an *-nto-qnx* case (QNX host triplets end in "
     "nto-qnx8.0.0)."),
]
MESON_RULES = [
    (re.compile(r"host_machine\.system\(\)\s*==\s*'linux'"),
     "Branch taken only on Linux; QNX reports a different host system."),
]
MAKE_RULES = [
    (re.compile(r'uname\s+-s|\$\(shell\s+uname'),
     "The Makefile checks the build host with uname; when cross-compiling for QNX the host is "
     "Linux, not the target."),
]


def detect(root):
    found = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not d.startswith(".") and d not in {"build", "_build"}]
        depth = os.path.relpath(dp, root).count(os.sep)
        for f in fns:
            if f in BUILD_FILES and depth <= 1:
                found.setdefault(BUILD_FILES[f], []).append(os.path.relpath(os.path.join(dp, f), root))
    order = ["cmake", "meson", "autotools", "bazel", "scons", "premake", "make"]
    primary = next((k for k in order if k in found), None)
    return primary, found


CMAKE_IF = re.compile(r"^\s*(else)?if\s*\((.*)", re.I)
CMAKE_SYS = re.compile(r"CMAKE_(HOST_)?SYSTEM(_NAME)?\s*\}?\s*(MATCHES|STREQUAL)\s+\"?([^\")]+)", re.I)
OS_NAME_IN_STRING = {"linux": "LINUX", "freebsd": "FREEBSD", "netbsd": "NETBSD", "openbsd": "OPENBSD",
                     "dragonfly": "DRAGONFLY", "darwin": "APPLE", "sunos": "SUN", "solaris": "SUN",
                     "aix": "AIX", "haiku": "HAIKU", "android": "ANDROID", "windows": "WINDOWS",
                     "cygwin": "CYGWIN", "gnu": "HURD", "emscripten": "WASM", "ios": "APPLE"}


def cmake_platform_list(line):
    """OS families an if()/elseif() tests for, when it is a platform list that leaves QNX out."""
    m = CMAKE_IF.match(line)
    if not m or re.search(r"qnx", line, re.I) or re.search(r"\bNOT\b", m.group(2)):
        return None
    cond = m.group(2)
    groups = set()
    for sm in CMAKE_SYS.finditer(cond):
        for w in re.split(r"[^A-Za-z]+", sm.group(4).lower()):
            if w in OS_NAME_IN_STRING:
                groups.add(OS_NAME_IN_STRING[w])
    for w in re.findall(r"\b[A-Z0-9_]+\b", re.sub(r"\"[^\"]*\"", "", cond)):
        if w in kb.CMAKE_OS_VARS:
            groups.add(kb.CMAKE_OS_VARS[w])
    if "UNIX" in groups:
        if len(groups) >= 2 and "OR" in cond.upper().split():
            # "UNIX OR MINGW" style lists: QNX matches UNIX, but such lists often guard
            # Linux/BSD-only code; report as low priority
            return groups
        return None
    has_sys = bool(CMAKE_SYS.search(cond))
    if (has_sys and groups) or len(groups) >= 2:
        return groups
    return None


def scan_build_files(root):
    findings = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if not d.startswith(".") and d not in {"build", "_build"}]
        for f in fns:
            rules = None
            if f == "CMakeLists.txt" or f.endswith(".cmake"):
                rules = CMAKE_RULES
            elif f in ("configure.ac", "configure.in") or f.endswith(".m4"):
                rules = AUTOTOOLS_RULES
            elif f in ("meson.build",):
                rules = MESON_RULES
            elif f in ("Makefile", "makefile", "GNUmakefile") or f.endswith(".mk"):
                rules = MAKE_RULES
            if not rules:
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root).replace("\\", "/")
            try:
                lines = open(p, encoding="utf-8", errors="replace").read().split("\n")
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                if line.lstrip().startswith("#") and rules is not AUTOTOOLS_RULES:
                    continue
                if rules is CMAKE_RULES and not CMAKE_RULES[0][0].search(line):
                    g = cmake_platform_list(line)
                    if g:
                        findings.append(Finding(
                            rel, i, kb.INFO if "UNIX" in g else kb.CHECK, "cmake-platform-list",
                            " / ".join(sorted(g)),
                            f"CMake platform test ({', '.join(sorted(g))}) without QNX. The QNX "
                            "toolchain sets CMAKE_SYSTEM_NAME to QNX, so this branch is "
                            + ("taken on QNX through UNIX; check that it fits." if "UNIX" in g
                               else "skipped on QNX. Add a QNX case if QNX supports the feature."),
                            "", "", line.strip()[:160]))
                        continue
                for rx, msg in rules:
                    if rx.search(line):
                        findings.append(Finding(rel, i, kb.CHECK, "build-linux", rx.pattern[:40], msg,
                                                "", "", line.strip()[:160]))
                        break
    return findings
