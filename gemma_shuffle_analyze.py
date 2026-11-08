"""Score gemma_shuffle.py: Recall per instance for each order of the file list, visible / hidden split,
how far down the shown list the picks are, and a sign test of listing order against the two shuffles.
Usage: python gemma_shuffle_analyze.py data/gemma_e2b_shuffle.json
"""
import json, sys, statistics as st
from math import comb

sys_argv = sys.argv
sys.argv = sys.argv[:1]
from gemma_shuffle import ORDERS, shown  # noqa: E402
sys.argv = sys_argv

KS = (1, 5, 10, 20)


def rec(rank, gold, k):
    return len(set(rank[:k]) & gold) / len(gold) if gold else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else float("nan")


def sign(pairs):
    d = [a - b for a, b in pairs]
    w, l = sum(x > 0 for x in d), sum(x < 0 for x in d)
    n, k = w + l, min(w, l)
    return w, l, min(1.0, 2 * sum(comb(n, j) for j in range(k + 1)) / 2 ** n) if n else 1.0


def main():
    res = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "data/gemma_e2b_shuffle.json"))
    inp = {x["id"]: x for x in json.load(open("data/llm_inputs.json"))}
    rows = []
    for r in res:
        x = inp[r["id"]]
        gold = set(x["gold"])
        vis = gold & set(x["snippets"])
        hid = gold - vis
        row = {"id": r["id"], "n_shown": None}
        for name, seed in ORDERS.items():
            rank = r[f"{name}_rank"]
            _, lines = shown(x, seed)
            pos = {}
            for i, p in enumerate(lines):
                pos.setdefault(p, i)
            row["n_shown"] = len(lines)
            idx = [pos[p] for p in rank if p in pos]
            for k in KS:
                row[f"{name}@{k}"] = rec(rank, gold, k)
            row[f"{name}_vis@10"] = rec(rank, vis, 10)
            row[f"{name}_hid@10"] = rec(rank, hid, 10)
            row[f"{name}_hid@20"] = rec(rank, hid, 20)
            row[f"{name}_pos"] = mean([i / max(1, len(lines) - 1) for i in idx])
            row[f"{name}_top10pct"] = mean([i < 0.1 * len(lines) for i in idx])
            row[f"{name}_inorder"] = len(idx) >= 5 and idx == sorted(idx)
            row[f"{name}_n"] = len(rank)
            row[f"{name}_empty"] = not rank
        for key, names in (("shuffled", ("shuffle0", "shuffle1")),):
            for m in [f"@{k}" for k in KS] + ["_vis@10", "_hid@10", "_hid@20"]:
                row[f"{key}{m}"] = mean([row[f"{n}{m}"] for n in names])
        rows.append(row)
    print(len(rows), "instances")
    for name in list(ORDERS) + ["shuffled"]:
        print(f"{name:9s} " + "  ".join(f"R@{k}={mean(r[f'{name}@{k}'] for r in rows):.3f}" for k in KS)
              + f"  vis@10={mean(r[f'{name}_vis@10'] for r in rows):.3f}"
              + f"  hid@10={mean(r[f'{name}_hid@10'] for r in rows):.3f}"
              + f"  hid@20={mean(r[f'{name}_hid@20'] for r in rows):.3f}")
    for name in ORDERS:
        print(f"{name:9s} picks per answer {mean(r[f'{name}_n'] for r in rows):.1f}, empty {sum(r[f'{name}_empty'] for r in rows)}, "
              f"mean position of picks {mean(r[f'{name}_pos'] for r in rows):.3f} (0 top, 1 bottom), "
              f"picks in first 10% {mean(r[f'{name}_top10pct'] for r in rows):.3f}, "
              f"answers in shown order {sum(r[f'{name}_inorder'] for r in rows)}/{len(rows)}, "
              f"median sec {st.median(x[f'{name}_sec'] for x in res):.0f}")
    for m in ("@10", "@20", "_vis@10", "_hid@10", "_hid@20"):
        pairs = [(r[f"listing{m}"], r[f"shuffled{m}"]) for r in rows
                 if r[f"listing{m}"] is not None and r[f"shuffled{m}"] is not None]
        w, l, p = sign(pairs)
        print(f"listing vs shuffled {m:7s} n={len(pairs)} higher {w} lower {l} p={p:.4f}")
    json.dump(rows, open("data/gemma_shuffle_analysis.json", "w"), indent=1)


if __name__ == "__main__":
    main()
