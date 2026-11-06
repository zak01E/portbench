"""Knowledge base: what QNX 8.0 has, and what Linux code tends to need.

Two sources:
1. data/qnx80_libc_index.json: every function listed in the QNX SDP 8.0 C Library
   Reference, with the headers from its synopsis and the library from its
   "Library:" section. It was retrieved from qnx.com on 2026-11-06.
2. LINUX_APIS / LINUX_HEADERS below: hand-written porting advice for
   Linux/glibc APIs. Each piece of advice names QNX replacements, and
   tests/test_kb.py checks that every replacement exists in the QNX index.
"""
import json
import os
from functools import lru_cache

DOCS_ROOT = "https://www.qnx.com/developers/docs/8.0/"
INDEX_URL = DOCS_ROOT + "com.qnx.doc.neutrino.lib_ref/topic/lib-a.html"
PORTS_URL = "https://github.com/qnx-ports/build-files/tree/main/ports"


@lru_cache(maxsize=1)
def qnx_index():
    path = os.path.join(os.path.dirname(__file__), "data", "qnx80_libc_index.json")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    out = {}
    for name, v in data["functions"].items():
        doc = v["doc"]
        if doc.startswith("../../"):
            doc = DOCS_ROOT + doc[len("../../"):]
        out[name] = {"headers": v["headers"], "libs": v["libs"], "class": v["class"], "doc": doc}
    return out


def qnx_has(name):
    return name in qnx_index()


def qnx_doc(name):
    e = qnx_index().get(name)
    return e["doc"] if e else None


# Severity levels, from most to least urgent.
BLOCKER = "blocker"   # will not compile or link on QNX as written
LINK = "link"         # compiles, but needs an extra -l option on QNX
CHECK = "check"       # builds, but the behaviour differs on QNX; review by hand
INFO = "info"

# --- Linux / glibc functions -------------------------------------------------
# "qnx_alt" lists QNX functions that the advice points to (checked by tests).
LINUX_APIS = [
    {"names": ["epoll_create", "epoll_create1", "epoll_ctl", "epoll_wait", "epoll_pwait"],
     "advice": "epoll is not in the QNX C library. Use poll(), or the epoll compatibility port "
               "maintained by QNX (qnx-ports/epoll, built from build-files/ports/epoll).",
     "qnx_alt": ["poll"], "evidence": PORTS_URL + "/epoll"},
    {"names": ["eventfd", "eventfd_read", "eventfd_write"],
     "advice": "eventfd is not in the QNX C library. A pipe created with pipe2(O_CLOEXEC|O_NONBLOCK) "
               "is the usual wake-up replacement.",
     "qnx_alt": ["pipe2"]},
    {"names": ["timerfd_create", "timerfd_settime", "timerfd_gettime"],
     "advice": "timerfd is not in the QNX C library. Use timer_create() with a sigevent (signal, "
               "thread or QNX pulse), or a poll() timeout.",
     "qnx_alt": ["timer_create", "poll"]},
    {"names": ["signalfd"],
     "advice": "signalfd is not in the QNX C library. Block the signals and receive them in a "
               "thread with sigwaitinfo() or sigtimedwait().",
     "qnx_alt": ["sigwaitinfo", "sigtimedwait"]},
    {"names": ["prctl"],
     "advice": "prctl() does not exist on QNX. For PR_SET_NAME use pthread_setname_np(); other "
               "options usually have no equivalent and should be guarded out.",
     "qnx_alt": ["pthread_setname_np"]},
    {"names": ["sysinfo", "get_nprocs", "get_nprocs_conf"],
     "advice": "sysinfo()/get_nprocs() are glibc-only. On QNX read the system page: "
               "_syspage_ptr->num_cpu gives the CPU count (see SYSPAGE_ENTRY).",
     "qnx_alt": ["_syspage_ptr", "SYSPAGE_ENTRY"]},
    {"names": ["sched_setaffinity", "sched_getaffinity", "pthread_setaffinity_np",
               "pthread_getaffinity_np", "pthread_attr_setaffinity_np"],
     "advice": "CPU affinity on QNX uses a run mask: ThreadCtl(_NTO_TCTL_RUNMASK_GET_AND_SET, ...) "
               "for a thread, posix_spawnattr_setrunmask() for a new process.",
     "qnx_alt": ["ThreadCtl", "posix_spawnattr_setrunmask"]},
    {"names": ["sched_getcpu"],
     "advice": "sched_getcpu() is not in the QNX C library; guard it out or return 0.", "qnx_alt": []},
    {"names": ["sendfile", "splice", "tee", "vmsplice", "copy_file_range"],
     "advice": "Zero-copy Linux calls are not in the QNX C library. Fall back to a read()/write() loop.",
     "qnx_alt": ["read", "write"]},
    {"names": ["dup3"],
     "advice": "dup3() is not in the QNX C library. Use dup2() then fcntl(fd, F_SETFD, FD_CLOEXEC).",
     "qnx_alt": ["dup2", "fcntl"]},
    {"names": ["getrandom", "getentropy", "arc4random", "arc4random_buf", "arc4random_uniform"],
     "advice": "Not in the QNX C library. Read /dev/urandom, which the QNX 'random' service provides.",
     "qnx_alt": ["random"]},
    {"names": ["memfd_create"],
     "advice": "memfd_create() does not exist on QNX. shm_open(SHM_ANON, ...) creates an anonymous "
               "shared-memory object.",
     "qnx_alt": ["shm_open"]},
    {"names": ["backtrace", "backtrace_symbols", "backtrace_symbols_fd"],
     "advice": "execinfo backtrace() is glibc-only and not in the QNX C library. Guard it out.",
     "qnx_alt": []},
    {"names": ["syscall"],
     "advice": "Raw Linux syscall numbers do not exist on QNX (a microkernel with message passing). "
               "Replace each syscall() with the matching library call.", "qnx_alt": []},
    {"names": ["vfork"],
     "advice": "vfork() is not in the QNX C library. Use posix_spawn() (preferred on QNX) or fork().",
     "qnx_alt": ["posix_spawn", "fork"]},
    {"names": ["clone", "unshare", "setns", "personality", "capset", "capget", "ptrace",
               "pivot_root", "umount2", "ioperm", "iopl", "reboot", "init_module", "delete_module"],
     "advice": "Linux-kernel-specific call with no QNX equivalent in the C library. Guard the "
               "feature out on QNX.", "qnx_alt": []},
    {"names": ["fallocate"],
     "advice": "Use posix_fallocate(), which QNX provides.", "qnx_alt": ["posix_fallocate"]},
    {"names": ["sync_file_range", "syncfs"],
     "advice": "Linux-only. Use fdatasync() or fsync().", "qnx_alt": ["fdatasync", "fsync"]},
    {"names": ["madvise"],
     "advice": "Use posix_madvise(), which QNX provides.", "qnx_alt": ["posix_madvise"]},
    {"names": ["explicit_bzero"],
     "advice": "Use memset_s(), which QNX provides and the compiler may not optimise away.",
     "qnx_alt": ["memset_s"]},
    {"names": ["memrchr", "rawmemchr", "strchrnul"],
     "advice": "GNU string extension not in the QNX C library. Add a small local implementation "
               "(memchr()/strchr() based).", "qnx_alt": ["memchr", "strchr"]},
    {"names": ["qsort_r"],
     "advice": "qsort_r() is not in the QNX C library (and its argument order differs between glibc "
               "and BSD anyway). Use qsort() with a context variable, or a local implementation.",
     "qnx_alt": ["qsort"]},
    {"names": ["secure_getenv", "__secure_getenv"],
     "advice": "glibc-only. Use getenv() (and check privileges yourself if that matters).",
     "qnx_alt": ["getenv"]},
    {"names": ["program_invocation_name", "program_invocation_short_name"],
     "advice": "glibc globals. Use getprogname() on QNX.", "qnx_alt": ["getprogname"], "kind": "symbol"},
    {"names": ["pthread_getattr_np"],
     "advice": "Not in the QNX C library. To find a thread's stack, keep the pthread_attr_t you "
               "created it with and use pthread_attr_getstack().", "qnx_alt": ["pthread_attr_getstack"]},
    {"names": ["getresuid", "getresgid", "setresuid", "setresgid"],
     "advice": "Not in the QNX C library. Use getuid()/geteuid() and setuid()/seteuid().",
     "qnx_alt": ["getuid", "geteuid", "setuid", "seteuid"]},
    {"names": ["error", "error_at_line"],
     "advice": "glibc <error.h> is not available. QNX provides the BSD err()/warn() family.",
     "qnx_alt": ["err", "warn"], "need_header": "error.h"},
    {"names": ["malloc_trim", "malloc_stats", "mallinfo2"],
     "advice": "glibc malloc extension not in the QNX C library; guard it out (QNX has mallopt()).",
     "qnx_alt": ["mallopt"]},
]

# --- headers ------------------------------------------------------------------
LINUX_HEADERS = {
    "sys/epoll.h": ("BLOCKER", "No <sys/epoll.h> in QNX; see epoll advice (poll() or the qnx-ports epoll port)."),
    "sys/eventfd.h": ("BLOCKER", "No <sys/eventfd.h> in QNX; use a pipe2() wake-up pipe."),
    "sys/timerfd.h": ("BLOCKER", "No <sys/timerfd.h> in QNX; use timer_create() or poll() timeouts."),
    "sys/signalfd.h": ("BLOCKER", "No <sys/signalfd.h> in QNX; use sigwaitinfo() in a thread."),
    "sys/prctl.h": ("BLOCKER", "No <sys/prctl.h> in QNX; use pthread_setname_np() for thread names."),
    "sys/sysinfo.h": ("BLOCKER", "No <sys/sysinfo.h> in QNX; use the system page (_syspage_ptr)."),
    "sys/sendfile.h": ("BLOCKER", "No sendfile on QNX; use read()/write()."),
    "sys/random.h": ("BLOCKER", "No getrandom() on QNX; read /dev/urandom."),
    "sys/syscall.h": ("BLOCKER", "Linux syscall numbers do not exist on QNX."),
    "sys/personality.h": ("BLOCKER", "Linux-only header."),
    "sys/fsuid.h": ("BLOCKER", "Linux-only header."),
    "sys/klog.h": ("BLOCKER", "Linux-only header."),
    "sys/vfs.h": ("BLOCKER", "Linux statfs header; use statvfs() from <sys/statvfs.h>."),
    "execinfo.h": ("BLOCKER", "glibc backtrace header, not in QNX; guard it out."),
    "error.h": ("BLOCKER", "glibc <error.h> is not in QNX; use <err.h> (err(), warn())."),
    "mcheck.h": ("BLOCKER", "glibc-only debugging header."),
    "gnu/libc-version.h": ("BLOCKER", "glibc-only header."),
    "features.h": ("CHECK", "glibc internal header; usually not needed, remove or guard."),
    "sys/inotify.h": ("LINK", "QNX provides inotify, but in libfsnotify: link with -l fsnotify."),
    "regex.h": ("LINK", "On QNX regcomp()/regexec() live in libregex: link with -l regex."),
}
LINUX_HEADER_PREFIXES = {
    "linux/": "Linux kernel UAPI header; QNX has no Linux kernel headers. Guard the code out or use the QNX API.",
    "asm/": "Linux architecture header; not available on QNX.",
    "bits/": "glibc internal header; include the public header instead.",
}

# --- link libraries -----------------------------------------------------------
SOCKET_FUNCS = ["socket", "bind", "listen", "accept", "connect", "send", "recv", "sendto", "recvfrom",
                "sendmsg", "recvmsg", "setsockopt", "getsockopt", "getaddrinfo", "freeaddrinfo",
                "gai_strerror", "getnameinfo", "gethostbyname", "gethostbyaddr", "inet_pton",
                "inet_ntop", "getpeername", "getsockname", "shutdown", "socketpair", "getifaddrs",
                "freeifaddrs", "if_nametoindex", "if_indextoname"]
SOCKET_ADVICE = ("On QNX the BSD socket API is in libsocket: link with -l socket. Real QNX ports add "
                 "-lsocket (e.g. libevent, dnsmasq, chrony in qnx-ports/build-files).")
SOCKET_EVIDENCE = PORTS_URL + "/libevent/common.mk"

# --- behaviour differences learned from real QNX ports -----------------------
# Each rule comes from a change the QNX team made in one of its ports; the evidence
# link points at that port. Matched as identifiers in code (not in comments).
UV = "https://github.com/qnx-ports/libuv/tree/qnx-v1.51.0/"
EV = "https://github.com/qnx-ports/libevent/tree/qnx-2.1.12-stable/"
PORT_RULES = [
    ({"getpriority", "setpriority"},
     "QNX priorities belong to threads, not processes; the QNX libuv port returns ENOSYS for "
     "process priority. Use pthread_setschedparam() for thread priority.", UV + "src/unix/core.c"),
    ({"SA_RESTART"},
     "The QNX libevent port turns SA_RESTART off (#ifndef __QNX__); check that interrupted "
     "calls are retried on EINTR.", EV + "signal.c"),
    ({"POLLRDHUP", "EPOLLRDHUP"},
     "POLLRDHUP does not exist on QNX; the QNX libuv port defines its replacement to 0.",
     UV + "src/unix/internal.h"),
    ({"_SC_IOV_MAX"},
     "The QNX libuv port skips sysconf(_SC_IOV_MAX) on QNX and relies on IOV_MAX.",
     UV + "src/unix/core.c"),
]

# Learned from the development set of ports (unbound, nghttp2, libwebsockets), 2026-11-06.
UB = "https://github.com/qnx-ports/unbound/tree/qnx-release-1.24.1/"
LWS = "https://github.com/qnx-ports/libwebsockets/tree/qnx-v4.5.8/"
PORT_RULES += [
    ({"TCP_KEEPIDLE", "TCP_KEEPINTVL", "TCP_KEEPCNT"},
     "QNX names these TCP keepalive options TCPCTL_KEEPIDLE / TCPCTL_KEEPINTVL / TCPCTL_KEEPCNT "
     "(from <netinet/tcp_var.h>); the QNX libwebsockets port maps them.",
     LWS + "lib/plat/unix/private-lib-plat-unix.h"),
    ({"BYTE_ORDER", "__BYTE_ORDER", "LITTLE_ENDIAN", "BIG_ENDIAN", "__LITTLE_ENDIAN", "__BIG_ENDIAN"},
     "glibc <endian.h> macros may be missing on QNX; QNX compilers define __LITTLEENDIAN__ or "
     "__BIGENDIAN__ (the QNX libwebsockets port derives BYTE_ORDER from them).",
     LWS + "lib/plat/unix/private-lib-plat-unix.h"),
]
# struct timeval used in a file that does not include <sys/time.h>: glibc pulls it in through
# other headers, QNX does not. The unbound and nghttp2 ports add the include in 5 places.
TIMEVAL_EVIDENCE = UB + "util/timehist.h"
# There is no separate libpthread to link on QNX (threads are in libc).
PTHREAD_LIB_EVIDENCE = LWS + "cmake/LwsCheckRequirements.cmake"

# Platform lists such as "#if defined(__linux__) || defined(__FreeBSD__)" that leave QNX out.
# The QNX libuv port added __QNX__ to four such lists in fs.c (utimensat/futimens paths).
PLATFORM_LIST_EVIDENCE = UV + "src/unix/fs.c"
OS_MACROS = ["__linux__", "BSD", "__FreeBSD__", "__NetBSD__", "__OpenBSD__", "__APPLE__", "__sun",
             "__DragonFly__", "_AIX", "__MVS__", "__HAIKU__", "__CYGWIN__"]
# Project-specific platform macros (HOST_OS_FREEBSD, GLOG_OS_LINUX, ZENOH_LINUX, OS_HAIKU ...):
# any identifier made of an OS name joined to other parts by "_". Groups map spellings to one OS.
OS_WORDS = {
    "linux": "LINUX", "freebsd": "FREEBSD", "netbsd": "NETBSD", "openbsd": "OPENBSD",
    "dragonfly": "DRAGONFLY", "bsd": "BSD", "darwin": "APPLE", "apple": "APPLE", "macos": "APPLE",
    "osx": "APPLE", "ios": "APPLE", "haiku": "HAIKU", "solaris": "SUN", "sunos": "SUN", "sun": "SUN",
    "aix": "AIX", "cygwin": "CYGWIN", "android": "ANDROID", "windows": "WINDOWS", "win32": "WINDOWS",
    "mingw": "WINDOWS", "hurd": "HURD", "emscripten": "WASM", "zos": "ZOS", "mvs": "ZOS",
    "unix": "UNIX", "posix": "UNIX",
}
# CMake: lists of OS names or OS variables in if()/elseif() that leave QNX out.
CMAKE_OS_VARS = {"APPLE": "APPLE", "WIN32": "WINDOWS", "MINGW": "WINDOWS", "MSVC": "WINDOWS",
                 "CYGWIN": "CYGWIN", "ANDROID": "ANDROID", "LINUX": "LINUX", "BSD": "BSD",
                 "IOS": "APPLE", "UNIX": "UNIX", "HAIKU": "HAIKU"}

# CMake feature checks for socket functions fail on QNX unless libsocket is linked.
CMAKE_SOCKET_CHECK_EVIDENCE = EV + "cmake/Macros.cmake"

# --- runtime paths --------------------------------------------------------------
PATH_RULES = [
    ("/proc/cpuinfo", "No /proc/cpuinfo on QNX; get CPU data from the system page (_syspage_ptr)."),
    ("/proc/meminfo", "No /proc/meminfo on QNX."),
    ("/proc/self/", "QNX /proc is not Linux procfs: per-process files such as /proc/self/maps, "
                    "/proc/self/status or /proc/self/exe do not exist with the Linux format."),
    ("/proc/", "QNX /proc is not Linux procfs; check every file read from it."),
    ("/sys/", "QNX has no sysfs (/sys)."),
    ("/dev/shm", "QNX has no /dev/shm directory; use shm_open() (objects appear under /dev/shmem)."),
    ("/etc/os-release", "/etc/os-release is a Linux distribution file."),
]
