"""Statistics for the learned ranker reported in the paper:
- per-instance sign tests against single heuristics (R@10, R@20), bootstrap 95% intervals (2,000 resamples);
- feature-group ablation (same cross-validation as learn_rank.py);
- recall by merge-base date (before / after June 2025) for the ranker, OS-mentions and Gemma 4 E2B.
Needs data/learn_results.json (learn_rank.py), data/eval_files.json, data/gemma_e2b_results.json.
"""
import json, random, statistics as st
from math import comb
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
import learn_rank as L

GROUPS = {"none": [], "graph": ["degree", "indegree", "nb_os_tokens", "ppr", "ppr_q"],
          "tokens": ["os_tokens", "has_os", "peer_tokens", "os_pct"], "qport": ["qport", "qport_blockers"],
          "path": ["depth", "depth_pct", "is_build", "is_header", "top_build", "name_hint"],
          "content": ["log_lines", "sys_includes", "any_includes", "qnx_clash_names"]}


def sign(a, b):
    d = [a[i] - b[i] for i in a]
    w, l = sum(x > 0 for x in d), sum(x < 0 for x in d)
    n, k = w + l, min(w, l)
    return w, l, 2 * sum(comb(n, j) for j in range(k + 1)) / 2 ** n


def main():
    ev = {x["id"]: x for x in json.load(open("data/eval_files.json"))}
    res = json.load(open("data/learn_results.json"))["logreg"]
    per = {}
    for r in res:
        per.setdefault(r["id"], []).append(r)
    lr = {k: {i: st.mean(x[f"R@{k}"] for x in v) for i, v in per.items()} for k in (10, 20)}
    ids = sorted(lr[10])
    rng = np.random.default_rng(0)

    def ci(vals):
        v = np.array([vals[i] for i in ids])
        bs = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(2000)]
        return f"{v.mean():.3f} [{np.percentile(bs, 2.5):.3f}, {np.percentile(bs, 97.5):.3f}]"

    for k in (10, 20):
        print(f"learned R@{k} {ci(lr[k])}")
        for b in ("os_mentions", "qport+os", "top_build+peers"):
            base = {i: ev[i][f"{b}@{k}"] for i in ids}
            w, l, p = sign(lr[k], base)
            print(f"  vs {b:16s} {ci(base)}  wins {w} losses {l} p={p:.4f}")
    insts = {i["id"]: i for i in json.load(open("data/portbench.json"))}
    g2 = {x["id"]: x for x in json.load(open("data/gemma_e2b_results.json"))}
    post = [i for i in ids if str(insts[i]["base_date"]) >= "2025-06"]
    for name, sel in (("before June 2025", [i for i in ids if i not in post]), ("after June 2025", post)):
        print(f"{name}: {len(sel)} instances, learned {st.mean(lr[10][i] for i in sel):.3f}, "
              f"OS-mentions {st.mean(ev[i]['os_mentions@10'] for i in sel):.3f}, "
              f"Gemma E2B paths {st.mean(g2[i]['tree@10'] for i in sel):.3f} (R@10)")
    print("truncated diffs among evaluated instances:", sum(bool(insts[i]["truncated"]) for i in ids))
    data = L.load()
    for g, drop in GROUPS.items():
        feats = [f for f in L.FEATS if f not in drop]
        rows = []
        for seed in (0, 1, 2):
            order_ids = [d["id"] for d in data]
            random.Random(seed).shuffle(order_ids)
            fold = {i: n % 5 for n, i in enumerate(order_ids)}
            for k in range(5):
                tr = [d for d in data if fold[d["id"]] != k]
                X, y, w = [], [], []
                for d in tr:
                    npos = sum(r["gold"] for r in d["rows"]); nneg = len(d["rows"]) - npos
                    for r in d["rows"]:
                        X.append([float(r[f]) for f in feats]); y.append(int(r["gold"]))
                        w.append(1 / npos if r["gold"] else 1 / nneg)
                m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000))
                m.fit(np.array(X), np.array(y), logisticregression__sample_weight=np.array(w))
                for d in data:
                    if fold[d["id"]] != k:
                        continue
                    p = m.predict_proba(np.array([[float(r[f]) for f in feats] for r in d["rows"]]))[:, 1]
                    rows.append(L.evaluate([d["rows"][i]["file"] for i in np.argsort(-p, kind="stable")], d))
        print(f"drop {g:8s} " + "  ".join(f"{k}={L.mean(r[k] for r in rows):.3f}"
                                         for k in ("R@10", "R@20", "vis@10", "hid@10", "hid@20")))


if __name__ == "__main__":
    main()
