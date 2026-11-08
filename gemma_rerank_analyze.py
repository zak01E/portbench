"""Score the two-stage pipeline: learned ranker shortlist (top 30) re-ranked by Gemma.
Usage: python gemma_rerank_analyze.py data/gemma_e4b_rerank.json
Rankings compared on the same 30-file shortlist (seed-0 cross-validation folds):
  learned  - the ranker's own order;
  gemma    - Gemma's list first, then the rest of the shortlist in the ranker's order;
  rrf      - reciprocal-rank fusion of the two orders (k = 60).
"""
import json, sys, statistics as st

from gemma_baseline import parse

KS = (1, 5, 10, 20)


def rec(rank, s, k):
    return len(set(rank[:k]) & s) / len(s) if s else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs)


def main():
    res = {r["id"]: r for r in json.load(open(sys.argv[1]))}
    inp = {x["id"]: x for x in json.load(open("data/rerank_inputs.json"))}
    rows = {m: [] for m in ("learned", "gemma", "rrf")}
    for iid, x in inp.items():
        short = x["shortlist"]
        # re-parse the raw answer with the current parser (numbered lines, bare list positions)
        g = parse(res[iid]["raw"], short, numbered=short) if iid in res else []
        res.get(iid, {})["rank"] = g
        gem = g + [f for f in short if f not in g]
        score = {}
        for lst in (short, gem):
            for i, f in enumerate(lst):
                score[f] = score.get(f, 0) + 1 / (60 + i)
        rrf = sorted(short, key=lambda f: -score[f])
        gold, hid = set(x["gold"]), set(x["hidden"])
        vis = gold - hid
        for m, order in (("learned", short), ("gemma", gem), ("rrf", rrf)):
            r = {f"R@{k}": rec(order, gold, k) for k in KS}
            r.update({"vis@10": rec(order, vis, 10), "hid@10": rec(order, hid, 10), "hid@20": rec(order, hid, 20)})
            rows[m].append(r)
    print(f"{len(inp)} instances, {len(res)} Gemma answers, "
          f"{sum(1 for r in res.values() if not r['rank'])} empty, median {st.median(r['sec'] for r in res.values())} s")
    for m, rs in rows.items():
        print(f"  {m:8s} " + "  ".join(f"{k}={mean(r[k] for r in rs):.3f}" for k in
                                       ("R@1", "R@5", "R@10", "R@20", "vis@10", "hid@10", "hid@20")))
    print("  avg files returned by Gemma:", round(st.mean(len(r["rank"]) for r in res.values()), 1))


if __name__ == "__main__":
    main()
