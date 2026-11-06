"""Per-gold-file analysis: where does the best simple baseline rank each gold file, by fix type."""
import json, random, statistics as st
from collections import Counter, defaultdict
from multiprocessing import Pool
from evaluate import candidates, read, strip_comments, OS_TOKENS, PEERS

def one(args):
    iid, s, inst = args
    root = s["dir"]
    cands = candidates(root)
    gold = {x["file"] for x in inst["sites"]} & set(cands)
    if not gold:
        return []
    rnd = random.Random(0); tie = {f: rnd.random() for f in cands}
    osc = {f: len(OS_TOKENS.findall(strip_comments(read(root, f)))) for f in cands}
    rank = sorted(cands, key=lambda f: (-osc[f], tie[f]))
    pos = {f: i + 1 for i, f in enumerate(rank)}
    kinds = defaultdict(set)
    for x in inst["sites"]:
        kinds[x["file"]].add(x["kind"])
    return [{"id": iid, "file": f, "rank": pos[f], "n": len(cands), "tokens": osc[f],
             "build": not f.endswith((".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".ipp", ".inl", ".inc")),
             "kinds": sorted(kinds[f])} for f in gold]

def main():
    insts = {i["id"]: i for i in json.load(open("data/portbench.json"))}
    srcs = json.load(open("data/sources.json"))
    jobs = [(i, s, insts[i]) for i, s in srcs.items() if s["status"] == "ok"]
    with Pool(7) as p:
        rows = [r for rs in p.map(one, jobs) for r in rs]
    json.dump(rows, open("data/gold_file_ranks.json", "w"), indent=0)
    print("gold files", len(rows), "build share", round(sum(r["build"] for r in rows) / len(rows), 3))
    print("gold files with no platform token", sum(r["tokens"] == 0 for r in rows))
    for name, sel in [("with tokens", [r for r in rows if r["tokens"] > 0]), ("no tokens", [r for r in rows if r["tokens"] == 0]),
                      ("build", [r for r in rows if r["build"]]), ("source", [r for r in rows if not r["build"]])]:
        print(f"{name:12s} n={len(sel):4d} top10={sum(r['rank'] <= 10 for r in sel) / len(sel):.2f} "
              f"median rank pct={st.median(r['rank'] / r['n'] for r in sel):.3f}")
    by = defaultdict(list)
    for r in rows:
        for k in r["kinds"]:
            by[k].append(r)
    for k, sel in sorted(by.items(), key=lambda kv: -len(kv[1])):
        print(f"kind {k:14s} n={len(sel):4d} top10={sum(r['rank'] <= 10 for r in sel) / len(sel):.2f} "
              f"no-token share={sum(r['tokens'] == 0 for r in sel) / len(sel):.2f}")

if __name__ == "__main__":
    main()
