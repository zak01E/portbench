"""Per-file features for a learned localization ranker (one row per candidate file).

Features use only the upstream tree at base_commit, never the QNX branch:
platform tokens, Unix-peer tokens, qport findings, path shape (depth, build file, header, name hints),
size, includes of system headers, and include-graph signals (degree, neighbours' tokens, PageRank).
Output: data/features.jsonl (one JSON object per instance with a list of file rows).
"""
import json, math, re, sys
from collections import defaultdict
from multiprocessing import Pool

from evaluate import candidates, read, strip_comments, OS_TOKENS, PEERS, SEV_W, run_scan
from graph_eval import build_graph, ppr

SRC_EXT = (".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".ipp", ".inl", ".inc")
HEADER_EXT = (".h", ".hh", ".hpp", ".hxx", ".inc", ".inl", ".ipp")
NAME_HINT = re.compile(r"platform|port|compat|config|os[_./-]|[_/-]os\b|sys|unix|posix|linux|thread|socket|net|time|"
                       r"signal|process|proc|file|fs|dl|mem|atomic|cpu|arch", re.I)
SYS_INC = re.compile(r'^\s*#\s*include\s*<(sys/|linux/|netinet/|arpa/|net/|asm/|bits/|execinfo|malloc\.h|alloca\.h|'
                     r'endian\.h|byteswap\.h|features\.h|pthread\.h|sched\.h|signal\.h|dlfcn\.h|poll\.h|termios\.h)', re.M)
ANY_INC = re.compile(r"^\s*#\s*include\s*<", re.M)
QNX_FIX = re.compile(r"\b(MIN|MAX|_INT32|_UINT32|cpu_set_t|timeval|PATH_MAX|O_CLOEXEC|MSG_NOSIGNAL|SO_REUSEPORT)\b")


def one(args):
    iid, s, inst = args
    root = s["dir"]
    cands = candidates(root)
    gold = {x["file"] for x in inst["sites"]} & set(cands)
    if not gold:
        return None
    texts = {f: read(root, f) for f in cands}
    clean = {f: strip_comments(t) for f, t in texts.items()}
    osc = {f: len(OS_TOKENS.findall(clean[f])) for f in cands}
    peer = {f: len(PEERS.findall(clean[f])) for f in cands}
    qp, qblock = defaultdict(float), defaultdict(int)
    try:
        for x in run_scan(root)["findings"]:
            qp[x.file] += SEV_W.get(x.severity, 1)
            qblock[x.file] += x.severity == "blocker"
    except Exception:  # noqa: BLE001
        pass
    adj = build_graph(cands, texts)
    nb = {f: sum(osc[g] for g in adj.get(f, ())) for f in cands}
    pr = ppr(cands, adj, {f: float(osc[f]) for f in cands})
    prq = ppr(cands, adj, {f: float(osc[f] + qp.get(f, 0)) for f in cands})
    indeg = defaultdict(int)
    for f in cands:
        for g in adj.get(f, ()):
            indeg[g] += 1
    n = len(cands)
    depth_rank = {f: i for i, f in enumerate(sorted(cands, key=lambda p: p.count("/")))}
    os_rank = {f: i for i, f in enumerate(sorted(cands, key=lambda p: -osc[p]))}
    rows = []
    for f in cands:
        lines = texts[f].count("\n") + 1
        is_src = f.endswith(SRC_EXT)
        rows.append({
            "file": f, "gold": f in gold, "hidden": f in gold and osc[f] == 0,
            "os_tokens": math.log1p(osc[f]), "has_os": osc[f] > 0, "peer_tokens": math.log1p(peer[f]),
            "qport": math.log1p(qp.get(f, 0)), "qport_blockers": math.log1p(qblock.get(f, 0)),
            "depth": f.count("/"), "depth_pct": depth_rank[f] / n, "os_pct": os_rank[f] / n,
            "is_build": not is_src, "is_header": f.endswith(HEADER_EXT),
            "top_build": (not is_src) and f.count("/") == 0, "name_hint": bool(NAME_HINT.search(f)),
            "log_lines": math.log1p(lines), "sys_includes": math.log1p(len(SYS_INC.findall(texts[f]))),
            "any_includes": math.log1p(len(ANY_INC.findall(texts[f]))),
            "qnx_clash_names": math.log1p(len(QNX_FIX.findall(clean[f]))),
            "degree": math.log1p(len(adj.get(f, ()))), "indegree": math.log1p(indeg[f]),
            "nb_os_tokens": math.log1p(nb[f]), "ppr": pr[f] * n, "ppr_q": prq[f] * n,
            "log_n_files": math.log(n),
        })
    return {"id": iid, "n_files": n, "rows": rows}


def main():
    insts = {i["id"]: i for i in json.load(open("data/portbench.json"))}
    srcs = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "data/sources.json"))
    jobs = [(i, s, insts[i]) for i, s in sorted(srcs.items()) if s["status"] == "ok"]
    with Pool(7) as p, open("data/features.jsonl", "w") as out:
        k = 0
        for r in p.imap_unordered(one, jobs):
            if r:
                out.write(json.dumps(r) + "\n"); k += 1
                print(k, r["id"], r["n_files"], flush=True)


if __name__ == "__main__":
    main()
