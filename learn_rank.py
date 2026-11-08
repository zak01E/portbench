"""Learned file ranker on data/features.jsonl, evaluated with project-level cross-validation.

Every instance (project) is in exactly one test fold; the model never sees a test project during
training. 5 folds, repeated with 3 random fold assignments; metrics are averaged per instance.
Models: logistic regression (standardised features, balanced classes) and gradient-boosted trees.
Writes data/learned_ranks.json (top 30 files per instance from the logistic model, seed 0) and
data/learn_log.txt.
"""
import json, random, statistics as st
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATS = ["os_tokens", "has_os", "peer_tokens", "qport", "qport_blockers", "depth", "depth_pct", "os_pct",
         "is_build", "is_header", "top_build", "name_hint", "log_lines", "sys_includes", "any_includes",
         "qnx_clash_names", "degree", "indegree", "nb_os_tokens", "ppr", "ppr_q", "log_n_files"]
KS = (1, 5, 10, 20)


def load():
    import gzip, os
    src = open("data/features.jsonl") if os.path.exists("data/features.jsonl") else gzip.open("data/features.jsonl.gz", "rt")
    data = [json.loads(l) for l in src]
    data.sort(key=lambda d: d["id"])
    return data


def matrix(insts):
    """Each instance gets the same total weight for its gold files and for its other files, so large
    repositories do not dominate training."""
    X, y, w = [], [], []
    for d in insts:
        npos = sum(r["gold"] for r in d["rows"]); nneg = len(d["rows"]) - npos
        for r in d["rows"]:
            X.append([float(r[f]) for f in FEATS]); y.append(int(r["gold"]))
            w.append(1 / npos if r["gold"] else 1 / nneg)
    return np.array(X), np.array(y), np.array(w)


def models():
    return {
        "logreg": lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000)),
        "boosted": lambda: HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                                          min_samples_leaf=40, random_state=0),
    }


def evaluate(rank, d):
    gold = {r["file"] for r in d["rows"] if r["gold"]}
    vis = {r["file"] for r in d["rows"] if r["gold"] and not r["hidden"]}
    hid = {r["file"] for r in d["rows"] if r["hidden"]}
    out = {f"R@{k}": len(set(rank[:k]) & gold) / len(gold) for k in KS}
    out["vis@10"] = len(set(rank[:10]) & vis) / len(vis) if vis else None
    out["hid@10"] = len(set(rank[:10]) & hid) / len(hid) if hid else None
    out["hid@20"] = len(set(rank[:20]) & hid) / len(hid) if hid else None
    out["R@30"] = len(set(rank[:30]) & gold) / len(gold)
    return out


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs)


def main():
    data = load()
    seen = set(json.load(open("data/qport_seen_repos.json")))
    forks = {i["id"]: i["fork"].split("/")[1] for i in json.load(open("data/portbench.json"))}
    log = open("data/learn_log.txt", "w")

    def say(*a):
        print(*a); print(*a, file=log)

    say(f"{len(data)} instances, {sum(len(d['rows']) for d in data)} files, "
        f"{sum(r['gold'] for d in data for r in d['rows'])} gold files")
    results = {m: [] for m in models()}
    top30 = {}
    for seed in (0, 1, 2):
        ids = [d["id"] for d in data]
        random.Random(seed).shuffle(ids)
        fold = {iid: i % 5 for i, iid in enumerate(ids)}
        for k in range(5):
            train = [d for d in data if fold[d["id"]] != k]
            test = [d for d in data if fold[d["id"]] == k]
            X, y, w = matrix(train)
            for name, make in models().items():
                m = make()
                if name == "logreg":
                    m.fit(X, y, logisticregression__sample_weight=w)
                else:
                    m.fit(X, y, sample_weight=w)
                for d in test:
                    p = m.predict_proba(np.array([[float(r[f]) for f in FEATS] for r in d["rows"]]))[:, 1]
                    order = [d["rows"][i]["file"] for i in np.argsort(-p, kind="stable")]
                    row = evaluate(order, d); row["id"] = d["id"]; row["seed"] = seed
                    row["unseen"] = forks[d["id"]] not in seen
                    results[name].append(row)
                    if name == "logreg" and seed == 0:
                        top30[d["id"]] = order[:30]
    for name, rows in results.items():
        for subset, sel in (("all", rows), ("unseen", [r for r in rows if r["unseen"]])):
            say(f"{name:8s} {subset:6s} " + "  ".join(f"{k}={mean(r[k] for r in sel):.3f}" for k in
                ("R@1", "R@5", "R@10", "R@20", "R@30", "vis@10", "hid@10", "hid@20"))
                + f"  (n={len(sel) // 3} instances x 3 seeds)")
    # spread across the three fold assignments
    for name, rows in results.items():
        per_seed = [mean(r["R@10"] for r in rows if r["seed"] == s) for s in (0, 1, 2)]
        say(f"{name} R@10 by seed: " + ", ".join(f"{v:.3f}" for v in per_seed))
    # feature weights of the logistic model trained on everything (for the paper)
    X, y, w = matrix(data)
    lr = models()["logreg"]().fit(X, y, logisticregression__sample_weight=w)
    coef = lr[-1].coef_[0]
    say("logreg standardised coefficients: " + ", ".join(f"{f} {c:+.2f}" for f, c in
                                                          sorted(zip(FEATS, coef), key=lambda t: -abs(t[1]))))
    json.dump(top30, open("data/learned_ranks.json", "w"))
    json.dump(results, open("data/learn_results.json", "w"))


if __name__ == "__main__":
    main()
