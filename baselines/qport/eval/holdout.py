"""Out-of-sample check: run qport on upstream releases that QNX later ported, and see
whether qport flags the places the QNX engineers changed.

None of these repositories was used to write the rules (the rules came from the QNX
C library reference and from the libuv/libevent ports only).

Usage: python eval/holdout.py <work dir>
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from qport.cli import run_scan  # noqa: E402
from qport.scan import to_dict  # noqa: E402

DEV = [  # seen while writing rules. name, qnx-ports branch, upstream repo, upstream tag
    ("mosquitto", "qnx_v2.0.15", "eclipse-mosquitto/mosquitto", "v2.0.15"),
    ("nghttp2", "qnx-1.64.0", "nghttp2/nghttp2", "v1.64.0"),
    ("dlt-daemon", "qnx-v2.18.10", "COVESA/dlt-daemon", "v2.18.10"),
    ("jansson", "qnx-v2.14", "akheron/jansson", "v2.14"),
    ("libyaml", "qnx-0.2.5", "yaml/libyaml", "0.2.5"),
    ("unbound", "qnx-release-1.24.1", "NLnetLabs/unbound", "release-1.24.1"),
    ("lighttpd1.4", "qnx_1.4.73", "lighttpd/lighttpd1.4", "lighttpd-1.4.73"),
    ("libwebsockets", "qnx-v4.5.8", "warmcat/libwebsockets", "v4.5.8"),
    ("libusb", "libusb-1.0.23", "libusb/libusb", "v1.0.23"),
]
# Frozen before looking at any of their diffs (2026-11-06): the honest test set.
TEST = [
    ("cJSON", "qnx-v1.7.18", "DaveGamble/cJSON", "v1.7.18"),
    ("iperf3", "qnx-3.7", "esnet/iperf", "3.7"),
    ("lldpd", "qnx-1.0.22", "lldpd/lldpd", "1.0.22"),
    ("gflags", "qnx_v2.2.2", "gflags/gflags", "v2.2.2"),
    ("glog", "qnx-v0.6.0", "google/glog", "v0.6.0"),
    ("brotli", "qnx-v1.1.0", "google/brotli", "v1.1.0"),
    ("check", "qnx-0.15.2", "libcheck/check", "0.15.2"),
    ("zenoh-pico", "qnx-1.5.0", "eclipse-zenoh/zenoh-pico", "1.5.0"),
    ("fribidi", "qnx_v1.0.16", "fribidi/fribidi", "v1.0.16"),
    ("libxml2", "qnx-2.13.5", "GNOME/libxml2", "v2.13.5"),
    ("rtl-sdr", "qnx_2.0.2", "osmocom/rtl-sdr", "v2.0.2"),
]
# Second test set, named in RESULTS.md and frozen on 2026-11-06 before v0.2 was written and before
# looking at any diff. iperf2, libdaemon and tftp-hpa were dropped because they have no GitHub
# upstream with release tags (rule decided before cloning). Lua and avahi have no exact base tag;
# the "mentions QNX" filter removes the version noise.
TEST2 = [
    ("c-ares", "qnx_v1.30.0", "c-ares/c-ares", "v1.30.0"),
    ("avahi", "qnx-0.9.x", "avahi/avahi", "v0.9-rc1"),
    ("sscep", "qnx-v0.10.0", "certnanny/sscep", "v0.10.0"),
    ("lua", "qnx_v5.4", "lua/lua", "v5.4.6"),
    ("rapidjson", "qnx-v1.1.0", "Tencent/rapidjson", "v1.1.0"),
    ("tinyxml2", "qnx_10.0.0", "leethomason/tinyxml2", "10.0.0"),
    ("pistache", "qnx-v0.4.26", "pistacheio/pistache", "v0.4.26"),
]
SKIP = re.compile(r"(^|/)(\.git|\.github|test|tests|doc|docs|examples?)(/|$)|qnx|nto", re.I)
CODE = re.compile(r"\.(c|h|cc|cpp|hpp|cxx)$|CMakeLists\.txt$|\.cmake$|configure\.ac$|meson\.build$|Makefile(\.am)?$")


def sh(*a, cwd=None):
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True, errors="replace")


def clone(url, branch, dest):
    if not os.path.isdir(dest):
        r = sh("git", "clone", "-q", "--depth", "1", "--branch", branch, url, dest)
        if r.returncode:
            return r.stderr.strip()[:200]
    return None


def sites_of(work, up, q):
    diff = sh("git", "diff", "--no-index", "-U0", up, q, cwd=work).stdout
    hunks, cur = [], None
    for line in diff.split("\n"):
        m = re.match(r"^--- a/(.*)", line)
        if m:
            cur = m.group(1)[len(up) + 1:]
            continue
        if line.startswith("+++"):
            continue
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? ", line)
        if m:
            if cur and CODE.search(cur) and not SKIP.search(cur):
                hunks.append([cur, int(m.group(1)), int(m.group(2) or 1), ""])
            else:
                hunks.append(None)
        elif hunks and hunks[-1] is not None and line[:1] in "+-":
            hunks[-1][3] += line[1:] + "\n"
    sites = []
    for f, a, n, txt in sorted(h for h in hunks if h):
        if sites and sites[-1][0] == f and a - sites[-1][2] <= 25:
            sites[-1][2] = a + max(n, 1)
            sites[-1][3] += txt
        else:
            sites.append([f, a, a + max(n, 1), txt])
    # Keep only changes that mention QNX: some qnx-ports branches are based on a slightly
    # different upstream commit than the tag, and those unrelated upstream edits must not count.
    sites = [s for s in sites if re.search(r"qnx|__nto|\bnto\b", s[3], re.I)]
    for s in sites:
        build = not re.search(r"\.(c|h|cc|cpp|hpp|cxx)$", s[0])
        s.append("packaging" if build and re.search(r"install\s*\(|INSTALL_TESTS|_tests\b", s[3], re.I)
                 else "porting")
    return sites


def main(work, which="dev"):
    os.makedirs(work, exist_ok=True)
    rows = []
    for name, qb, upr, tag in {"test": TEST, "test2": TEST2}.get(which, DEV):
        up, q = f"ho-up-{name}", f"ho-qnx-{name}"
        e1 = clone(f"https://github.com/{upr}.git", tag, os.path.join(work, up))
        e2 = clone(f"https://github.com/qnx-ports/{name}.git", qb, os.path.join(work, q))
        if e1 or e2:
            rows.append({"name": name, "error": e1 or e2})
            print(name, "clone error", e1 or e2)
            continue
        sites = sites_of(work, up, q)
        res = run_scan(os.path.join(work, up))
        fs = [to_dict(f) for f in res["findings"]]
        detail = []
        hit = 0
        pack = sum(1 for x in sites if x[4] == "packaging")
        for f, a, b, txt, kind in sites:
            if kind == "packaging":
                detail.append({"file": f, "lines": [a, b], "kind": kind})
                continue
            near = [x for x in fs if x["file"] == f and x["line"] - 3 <= b and max(x["end_line"], x["line"]) + 3 >= a]
            hit += bool(near)
            detail.append({"file": f, "lines": [a, b], "kind": kind, "change": txt[:400], "flagged": [(x["severity"], x["rule"], x["symbol"]) for x in near][:3]})
        sev = {}
        for x in fs:
            sev[x["severity"]] = sev.get(x["severity"], 0) + 1
        rows.append({"name": name, "fix_sites": len(sites) - pack, "packaging_sites": pack, "flagged": hit,
                     "findings": sev, "sites": detail})
        print(f"{name}: {hit}/{len(sites) - pack} porting sites flagged (+{pack} test-install sites); findings {sev}", flush=True)
    tot = sum(r.get("fix_sites", 0) for r in rows)
    hit = sum(r.get("flagged", 0) for r in rows)
    print(f"TOTAL {hit}/{tot}")
    with open(os.path.join(os.path.dirname(__file__), f"holdout_{which}.json"), "w") as fh:
        json.dump({"total_sites": tot, "flagged": hit, "repos": rows}, fh, indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "dev")
