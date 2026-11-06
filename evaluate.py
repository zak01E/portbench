"""Step 5: file-level localization baselines on PortBench.

Task: given an upstream repository at the base commit and the target "QNX 8.0", rank its source
and build files by how likely they need a change. Gold = files with at least one QNX fix site.
"""
import json, os, re, sys, random, statistics as st
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "baselines", "qport")))
from qport.cli import run_scan  # noqa: E402
from qport.scan import strip_comments  # noqa: E402

CAND = re.compile(r"\.(c|h|cc|cpp|cxx|hpp|hh|hxx|ipp|inl|inc)$|(^|/)(CMakeLists\.txt|[^/]*\.cmake|configure\.ac|configure\.in|Makefile\.am|Makefile\.in|Makefile|GNUmakefile|[^/]*\.mk|meson\.build)$")
from label import NOISE, TEST, QNX  # noqa: E402
OS_TOKENS = re.compile(r"__linux__|__linux\b|__APPLE__|__MACH__|_WIN32|_WIN64|__FreeBSD__|__NetBSD__|__OpenBSD__|"
                       r"__DragonFly__|\bBSD\b|__sun\b|__HAIKU__|__CYGWIN__|__ANDROID__|_AIX|__unix__|"
                       r"CMAKE_SYSTEM_NAME|CMAKE_HOST_SYSTEM|\bAPPLE\b|\bWIN32\b|\bLINUX\b|\bUNIX\b|"
                       r"\w*_OS_\w+|\w+_(LINUX|DARWIN|MACOS|FREEBSD|WINDOWS|WIN32|BSD)\b|host_machine\.system|\*-linux\*")
PEERS = re.compile(r"__APPLE__|__MACH__|__FreeBSD__|__NetBSD__|__OpenBSD__|__DragonFly__|BSD|__sun|_AIX|__HAIKU__|__CYGWIN__|\w*_OS_(BSD|FREEBSD|NETBSD|OPENBSD|DARWIN|MACOS|OSX|SOLARIS|AIX|HAIKU)\w*|\"(FreeBSD|Darwin|OpenBSD|NetBSD|SunOS|AIX)")
SEV_W = {"blocker": 4, "link": 1, "check": 2, "info": 0.5}
KS = (1, 5, 10, 20)

def candidates(root):
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != ".git"]
        for f in fns:
            rel = os.path.relpath(os.path.join(dp, f), root).replace("\\", "/")
            if CAND.search(rel) and not NOISE.search(rel) and not TEST.search(rel) and not QNX.search(rel):
                out.append(rel)
    return out

def read(root, rel):
    try:
        with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""

def recall_at(rank, gold, k):
    return len(set(rank[:k]) & gold) / len(gold)

def one(args):
    iid, s, inst, seen = args
    root = s["dir"]
    cands = candidates(root)
    gold = {x["file"] for x in inst["sites"]} & set(cands)
    if not gold:
        return None
    rnd = random.Random(0)
    texts = {f: strip_comments(read(root, f)) for f in cands}
    osc = {f: len(OS_TOKENS.findall(texts[f])) for f in cands}
    peer = {f: len(PEERS.findall(texts[f])) for f in cands}
    top_build = {f: (f.count("/") == 0 and not re.search(r"\.(c|h|cc|cpp|cxx|hpp|hh|hxx|ipp|inl|inc)$", f)) for f in cands}
    try:
        res = run_scan(root)
        qp = defaultdict(float)
        for f in res["findings"]:
            qp[f.file] += SEV_W.get(f.severity, 1)
    except Exception as e:  # noqa: BLE001
        print(iid, "qport failed", e, flush=True); qp = {}
    tie = {f: rnd.random() for f in cands}
    ranks = {
        "random": sorted(cands, key=lambda f: tie[f]),
        "os_mentions": sorted(cands, key=lambda f: (-osc[f], tie[f])),
        "unix_peers": sorted(cands, key=lambda f: (-peer[f], -osc[f], tie[f])),
        "top_build+peers": sorted(cands, key=lambda f: (-top_build[f], -peer[f], -osc[f], tie[f])),
        "qport": sorted(cands, key=lambda f: (-qp.get(f, 0), tie[f])),
        "qport+os": sorted(cands, key=lambda f: (-(qp.get(f, 0) + osc[f]), tie[f])),
    }
    row = {"id": iid, "n_files": len(cands), "n_gold": len(gold), "seen_by_qport": inst["fork"].split("/")[1] in seen,
           "gold_with_os_tokens": sum(osc[f] > 0 for f in gold) / len(gold)}
    for m, r in ranks.items():
        for k in KS:
            row[f"{m}@{k}"] = recall_at(r, gold, k)
    return row


METHODS = ("random", "os_mentions", "unix_peers", "top_build+peers", "qport", "qport+os")


def summary(rows):
    for subset, sel in [("all", rows), ("unseen", [r for r in rows if not r["seen_by_qport"]])]:
        print()
        print(f"{subset}: {len(sel)} instances, median files {st.median(r['n_files'] for r in sel)}, "
              f"median gold {st.median(r['n_gold'] for r in sel)}, gold files with platform tokens "
              f"{st.mean(r['gold_with_os_tokens'] for r in sel):.2f}")
        for m in METHODS:
            print(f"  {m:16s} " + "  ".join(f"R@{k}={st.mean(r[f'{m}@{k}'] for r in sel):.3f}" for k in KS))


def main():
    from multiprocessing import Pool
    insts = {i["id"]: i for i in json.load(open("data/portbench.json"))}
    srcs = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "data/sources.json"))
    seen = set(json.load(open("data/qport_seen_repos.json")))
    jobs = [(iid, s, insts[iid], seen) for iid, s in sorted(srcs.items()) if s["status"] == "ok"]
    rows = []
    with Pool(7) as pool:
        for row in pool.imap_unordered(one, jobs):
            if row:
                rows.append(row)
                print(row["id"], row["n_files"], row["n_gold"], {m: round(row[f"{m}@10"], 2) for m in METHODS}, flush=True)
    rows.sort(key=lambda r: r["id"].lower())
    json.dump(rows, open("data/eval_files.json", "w"), indent=1)
    summary(rows)


if __name__ == "__main__":
    main()
