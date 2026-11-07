"""Analyse the Gemma baseline output (data/gemma_e2b_results.json) against the other baselines.

- Recall@k for the two prompts, and for the same instances under random and OS-mentions.
- Visible / hidden split: a gold file is visible if it is among the files with platform lines
  (the `snippets` keys of llm_inputs.json: the top 60 files with at least one platform token).
- Copying: share of answers whose paths appear in the same order as in the input list.
- Fusion: Gemma's list first, then the OS-mentions order to fill up to 20, and reciprocal-rank fusion.
"""
import json, sys, statistics as st

KS = (1, 5, 10, 20)


def rec(rank, gold, k):
    return len(set(rank[:k]) & gold) / len(gold) if gold else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else float("nan")


def main():
    res = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "data/gemma_e2b_results.json"))
    inp = {x["id"]: x for x in json.load(open("data/llm_inputs.json"))}
    ev = {x["id"]: x for x in json.load(open("data/eval_files.json"))}
    rows = []
    for r in res:
        x = inp[r["id"]]
        gold = set(x["gold"])
        vis = gold & set(x["snippets"])
        hid = gold - vis
        os_order = list(x["snippets"]) + [c for c in x["candidates"] if c not in x["snippets"]]
        pos = {c: i for i, c in enumerate(x["candidates"])}
        row = {"id": r["id"]}
        for m in ("tree", "rerank"):
            rank = r[f"{m}_rank"]
            idx = [pos[p] for p in rank]
            row[f"{m}_copy"] = len(rank) >= 5 and idx == sorted(idx)
            fill = rank + [c for c in os_order if c not in rank]
            rrf = {}
            for lst in (rank, os_order):
                for i, c in enumerate(lst):
                    rrf[c] = rrf.get(c, 0) + 1 / (60 + i)
            fused = sorted(rrf, key=lambda c: -rrf[c])
            inter = []  # alternate: OS-mentions file, Gemma file, ...
            for a, b in zip(os_order, rank + [c for c in os_order if c not in rank]):
                for c in (a, b):
                    if c not in inter:
                        inter.append(c)
            for k in KS:
                row[f"{m}@{k}"] = rec(rank, gold, k)
                row[f"{m}+fill@{k}"] = rec(fill, gold, k)
                row[f"{m}+rrf@{k}"] = rec(fused, gold, k)
                row[f"{m}+inter@{k}"] = rec(inter, gold, k)
            row[f"{m}_vis@10"] = rec(rank, vis, 10)
            row[f"{m}_hid@10"] = rec(rank, hid, 10)
            row[f"{m}_hid@20"] = rec(rank, hid, 20)
            row[f"{m}+inter_vis@10"] = rec(inter, vis, 10)
            row[f"{m}+inter_hid@10"] = rec(inter, hid, 10)
            row[f"{m}+inter_hid@20"] = rec(inter, hid, 20)
        for b in ("random", "os_mentions"):
            for k in KS:
                row[f"{b}@{k}"] = ev[r["id"]][f"{b}@{k}"]
        row["os_vis@10"] = rec(os_order, vis, 10)
        row["os_hid@10"] = rec(os_order, hid, 10)
        row["os_hid@20"] = rec(os_order, hid, 20)
        rows.append(row)
    print(f"{len(rows)} instances")
    for m in ("random", "os_mentions", "tree", "rerank", "tree+fill", "rerank+fill", "tree+rrf", "rerank+rrf", "tree+inter", "rerank+inter"):
        print(f"  {m:12s} " + "  ".join(f"R@{k}={mean(r[f'{m}@{k}'] for r in rows):.3f}" for k in KS))
    for m in ("os", "tree", "rerank", "tree+inter", "rerank+inter"):
        print(f"  {m:12s} visible R@10 {mean(r[f'{m}_vis@10'] for r in rows):.3f}  hidden R@10 "
              f"{mean(r[f'{m}_hid@10'] for r in rows):.3f}  hidden R@20 {mean(r[f'{m}_hid@20'] for r in rows):.3f}")
    for m in ("tree", "rerank"):
        print(f"  {m}: answers in input order (5+ paths) {sum(r[f'{m}_copy'] for r in rows)}/{len(rows)}")
    secs = [r[f"{m}_sec"] for r in res for m in ("tree", "rerank")]
    print(f"  median seconds per prompt {st.median(secs):.0f} (CPU, llama.cpp, Q4_0)")
    json.dump(rows, open("data/gemma_analysis.json", "w"), indent=1)


if __name__ == "__main__":
    main()
