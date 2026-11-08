"""Order-only baselines on the Gemma inputs (data/llm_inputs.json):
- listing order: the candidate files in the order they are listed (os.walk: top-level files first);
- shallow-first: files sorted by directory depth, ties in listing order.
Reports Recall@k on all gold files and recall on visible / hidden gold files (per-instance averages).
"""
import json, statistics as st
from collections import defaultdict


def rec(rank, s, k):
    return len(set(rank[:k]) & s) / len(s)


def main():
    tokens = defaultdict(dict)
    for r in json.load(open("data/gold_file_ranks.json")):
        tokens[r["id"]][r["file"]] = r["tokens"]
    inp = json.load(open("data/llm_inputs.json"))
    orders = {"listing order": lambda x: x["candidates"],
              "shallow-first": lambda x: sorted(x["candidates"], key=lambda p: p.count("/"))}
    for name, order in orders.items():
        a = {k: [] for k in (1, 5, 10, 20)}
        vis, hid10, hid20 = [], [], []
        for x in inp:
            o, gold, t = order(x), set(x["gold"]), tokens[x["id"]]
            v = {f for f, c in t.items() if c > 0}
            h = {f for f, c in t.items() if c == 0}
            for k in a:
                a[k].append(rec(o, gold, k))
            if v:
                vis.append(rec(o, v, 10))
            if h:
                hid10.append(rec(o, h, 10)); hid20.append(rec(o, h, 20))
        print(f"{name:14s} " + "  ".join(f"R@{k}={st.mean(v):.3f}" for k, v in a.items())
              + f" | visible R@10 {st.mean(vis):.3f} hidden R@10 {st.mean(hid10):.3f} R@20 {st.mean(hid20):.3f}")


if __name__ == "__main__":
    main()
