from qport.scan import scan_text

SRC = r'''
#include <sys/epoll.h>
#include <regex.h>
#include <stdio.h>
// epoll_wait(x) in a comment must be ignored
static const char *p = "/proc/cpuinfo";
int f(void) {
    int e = epoll_create1(0);
    obj.connect(1);          /* member call, not the socket API */
    int s = socket(1, 2, 3);
#ifdef __QNXNTO__
    int q = eventfd(0, 0);   /* already handled for QNX */
#else
    int r = eventfd(0, 0);   /* the non-QNX branch: also fine */
#endif
#ifdef __linux__
    prctl(1);                /* Linux-only branch */
#endif
    regcomp(0, 0, 0);
    return e + s;
}
'''


def test_scan_finds_the_right_things():
    fs = scan_text(SRC, "x.c").findings
    got = {(f.symbol, f.severity) for f in fs}
    assert ("sys/epoll.h", "blocker") in got
    assert ("regex.h", "link") in got
    assert ("epoll_create1", "blocker") in got
    assert ("socket", "link") in got
    assert ("regex", "link") in got
    assert ("prctl", "info") in got
    assert not any(f.symbol == "eventfd" for f in fs)
    assert not any(f.symbol == "epoll_wait" for f in fs)
    assert sum(1 for f in fs if f.symbol == "socket") == 1
    assert any(f.rule == "linux-path" for f in fs)


def test_project_platform_macros():
    from qport.scan import scan_text, os_groups
    assert os_groups("defined(HOST_OS_FREEBSD) || defined(GLOG_OS_LINUX)") == {"FREEBSD", "LINUX"}
    assert os_groups("defined(HAVE_LINUX_FUTEX_H)") == set()
    src = "#if defined(__linux__)\n#define X_LINUX\n#elif defined(__APPLE__)\n#define X_MAC\n" \
          "#elif defined(__FreeBSD__)\n#define X_BSD\n#else\n#error unsupported\n#endif\n"
    rules = [f.rule for f in scan_text(src, "a.h").findings]
    assert "platform-chain" in rules
    ok = src.replace("#else", "#elif defined(__QNX__)\n#define X_QNX\n#else")
    assert "platform-chain" not in [f.rule for f in scan_text(ok, "a.h").findings]


def test_cmake_platform_list():
    from qport.buildsys import cmake_platform_list
    assert cmake_platform_list('if(CMAKE_SYSTEM_NAME MATCHES "FreeBSD|OpenBSD")')
    assert cmake_platform_list("elseif(APPLE OR WIN32)")
    assert not cmake_platform_list('if(CMAKE_SYSTEM_NAME MATCHES "QNX|Linux")')
    assert not cmake_platform_list("if(UNIX)")
    assert not cmake_platform_list("if(NOT WIN32)")
