"""Graph baselines: does the include graph help find the gold files that carry no platform token?

For each instance we build a file graph over the candidates:
- an edge for every `#include` that resolves to a candidate file (path-suffix match);
- an edge between a source file and the header with the same stem (foo.c <-> foo.h).
Seeds are the OS-mentions scores (optionally plus qport). We then rank by:
- inc_neighbors: own platform tokens first, then the sum of the neighbours' tokens;
- ppr: personalized PageRank on the undirected graph, seeded by the token counts;
- os+ppr: token count plus a PPR bonus.
We also report recall restricted to gold files with and without platform tokens.
"""
import json, os, re, sys, random, statistics as st
from collections import defaultdict
from multiprocessing import Pool

from evaluate import candidates, read, strip_comments, OS_TOKENS, KS, SEV_W, run_scan

INC = re.compile(r'^\s*#\s*include\s*[<"]([^">]+)[">]', re.M)
SRC_EXT = (".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".ipp", ".inl", ".inc")


def build_graph(cands, texts):
    by_base = defaultdict(list)
    for f in cands:
        by_base[f.rsplit("/", 1)[-1]].append(f)
    adj = defaultdict(set)
    for f in cands:
        if not f.endswith(SRC_EXT):
            continue
        for inc in INC.findall(texts[f]):
            inc = inc.replace("\\", "/").lstrip("./")
            hits = [g for g in by_base.get(inc.rsplit("/", 1)[-1], []) if g.endswith(inc) and g != f]
            if len(hits) > 1:  # prefer the header next to the includer
                d = f.rsplit("/", 1)[0] if "/" in f else ""
                near = [g for g in hits if g.startswith(d)]
                hits = near or hits
            for g in hits[:2]:
                adj[f].add(g); adj[g].add(f)
    stems = defaultdict(list)
    for f in cands:
        if f.endswith(SRC_EXT):
            stems[f.rsplit(".", 1)[0]].append(f)
    for group in stems.values():
        for a in group:
            for b in group:
                if a != b:
                    adj[a].add(b)
    return adj


def ppr(cands, adj, seed, alpha=0.3, iters=30):
    tot = sum(seed.values())
    if tot == 0:
        return {f: 0.0 for f in cands}
    p = {f: seed[f] / tot for f in cands}
    r = dict(p)
    for _ in range(iters):
        nxt = {f: alpha * p[f] for f in cands}
        for f in cands:
            nb = adj.get(f)
            if nb and r[f]:
                share = (1 - alpha) * r[f] / len(nb)
                for g in nb:
                    nxt[g] += share
            elif r[f]:
                nxt[f] += (1 - alpha) * r[f]
        r = nxt
    return r


def one(args):
    iid, s, inst = args
    root = s["dir"]
    cands = candidates(root)
    gold = {x["file"] for x in inst["sites"]} & set(cands)
    if not gold:
        return None
    rnd = random.Random(0); tie = {f: rnd.random() for f in cands}
    texts = {f: read(root, f) for f in cands}
    clean = {f: strip_comments(t) for f, t in texts.items()}
    osc = {f: len(OS_TOKENS.findall(clean[f])) for f in cands}
    try:
        qp = defaultdict(float)
        for x in run_scan(root)["findings"]:
            qp[x.file] += SEV_W.get(x.severity, 1)
    except Exception:  # noqa: BLE001
        qp = defaultdict(float)
    adj = build_graph(cands, texts)
    nb = {f: sum(osc[g] for g in adj.get(f, ())) for f in cands}
    pr = ppr(cands, adj, {f: float(osc[f]) for f in cands})
    pr_q = ppr(cands, adj, {f: float(osc[f] + qp.get(f, 0)) for f in cands})
    maxpr = max(pr.values()) or 1.0
    ranks = {
        "os_mentions": sorted(cands, key=lambda f: (-osc[f], tie[f])),
        "inc_neighbors": sorted(cands, key=lambda f: (-osc[f], -nb[f], tie[f])),
        "ppr": sorted(cands, key=lambda f: (-pr[f], tie[f])),
        "os+ppr": sorted(cands, key=lambda f: (-(osc[f] + 5 * pr[f] / maxpr), tie[f])),
        "ppr(os+qport)": sorted(cands, key=lambda f: (-pr_q[f], tie[f])),
    }
    # two-stage: alternate between the token ranking and the graph ranking
    inter, seen_ = [], set()
    for a, b in zip(ranks["os_mentions"], ranks["ppr(os+qport)"]):
        for f in (a, b):
            if f not in seen_:
                seen_.add(f); inter.append(f)
    ranks["interleave"] = inter
    tok_gold = {f for f in gold if osc[f] > 0}
    notok_gold = gold - tok_gold
    deg = [len(adj.get(f, ())) for f in cands]
    row = {"id": iid, "n_files": len(cands), "n_gold": len(gold), "n_notok": len(notok_gold),
           "edges": sum(deg) // 2, "isolated_share": sum(d == 0 for d in deg) / len(cands),
           "notok_gold_with_tok_neighbor": sum(nb[f] > 0 for f in notok_gold),
           "notok_gold_with_qport": sum(qp.get(f, 0) > 0 for f in notok_gold),
           "notok_cands": sum(osc[f] == 0 for f in cands),
           "notok_cands_with_qport": sum(osc[f] == 0 and qp.get(f, 0) > 0 for f in cands),
           "notok_cands_with_tok_neighbor": sum(osc[f] == 0 and nb[f] > 0 for f in cands)}
    for m, r in ranks.items():
        top = {k: set(r[:k]) for k in KS}
        for k in KS:
            row[f"{m}@{k}"] = len(top[k] & gold) / len(gold)
            row[f"{m}@{k}_notok_hits"] = len(top[k] & notok_gold)
            row[f"{m}@{k}_tok_hits"] = len(top[k] & tok_gold)
    row["n_tok"] = len(tok_gold)
    return row


METHODS = ("os_mentions", "inc_neighbors", "ppr", "os+ppr", "ppr(os+qport)", "interleave")


def main():
    insts = {i["id"]: i for i in json.load(open("data/portbench.json"))}
    srcs = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "data/sources.json"))
    jobs = [(i, s, insts[i]) for i, s in sorted(srcs.items()) if s["status"] == "ok"]
    with Pool(7) as p:
        rows = [r for r in p.map(one, jobs) if r]
    json.dump(rows, open("data/eval_graph.json", "w"), indent=1)
    n_tok = sum(r["n_tok"] for r in rows); n_no = sum(r["n_notok"] for r in rows)
    print(f"{len(rows)} instances; gold files with tokens {n_tok}, without {n_no}")
    print(f"median edges {st.median(r['edges'] for r in rows)}, median isolated share {st.median(r['isolated_share'] for r in rows):.2f}")
    print(f"no-token gold files with a token-bearing neighbour: {sum(r['notok_gold_with_tok_neighbor'] for r in rows)}/{n_no}"
          f" (all no-token candidates: {sum(r['notok_cands_with_tok_neighbor'] for r in rows)}/{sum(r['notok_cands'] for r in rows)})")
    print(f"no-token gold files with a qport finding: {sum(r['notok_gold_with_qport'] for r in rows)}/{n_no}"
          f" (all no-token candidates: {sum(r['notok_cands_with_qport'] for r in rows)}/{sum(r['notok_cands'] for r in rows)})")
    for m in METHODS:
        print(f"  {m:14s} " + "  ".join(f"R@{k}={st.mean(r[f'{m}@{k}'] for r in rows):.3f}" for k in KS)
              + f" | top10 tok {sum(r[f'{m}@10_tok_hits'] for r in rows) / n_tok:.2f}"
              + f" notok {sum(r[f'{m}@10_notok_hits'] for r in rows) / n_no:.3f}"
              + f" | top20 notok {sum(r[f'{m}@20_notok_hits'] for r in rows) / n_no:.3f}")
    sel = [r for r in rows if r["n_notok"]]; tok = [r for r in rows if r["n_tok"]]
    print(f"per-instance averages ({len(sel)} instances with no-token gold files, {len(tok)} with token gold files)")
    for m in METHODS:
        print(f"  {m:14s} no-token R@10 {st.mean(r[f'{m}@10_notok_hits'] / r['n_notok'] for r in sel):.3f}"
              f" R@20 {st.mean(r[f'{m}@20_notok_hits'] / r['n_notok'] for r in sel):.3f}"
              f" | token R@10 {st.mean(r[f'{m}@10_tok_hits'] / r['n_tok'] for r in tok):.3f}")


if __name__ == "__main__":
    main()
