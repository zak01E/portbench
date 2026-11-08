"""Does Gemma 4 E2B depend on the order of the file list? (paths-only prompt)

The prompt of gemma_baseline.py (mode "tree") is run three times per instance on the same backend:
  listing  - the list in its original order (control);
  shuffle0, shuffle1 - the same lines in a random order (fixed seeds).
Only the order of the lines changes: the same files are shown, truncated the same way.
Usage: python gemma_shuffle.py llm_inputs.json <gemma-4-e2b-it dir>
Output: GEMMA_OUT (default gemma_e2b_shuffle.json), one row per instance. Scored by gemma_shuffle_analyze.py.
"""
import json, os, random, time

from gemma_baseline import INPUT, make_generator, parse, prompt, safe_generate

ORDERS = {"listing": None, "shuffle0": 0, "shuffle1": 1}
MARK = "Files:\n"


def shown(inst, seed):
    """The (head of the prompt, list of path lines) in the order given by seed; None keeps the listing."""
    head, body = prompt(inst, "tree").split(MARK, 1)
    lines = body.split("\n")
    if seed is not None:
        random.Random(f"{seed}:{inst['id']}").shuffle(lines)
    return head, lines


def main():
    generate = make_generator()
    data = json.load(open(INPUT))
    out_path = os.environ.get("GEMMA_OUT", "gemma_e2b_shuffle.json")
    res = json.load(open(out_path)) if os.path.exists(out_path) else []
    done = {r["id"] for r in res}
    for inst in data:
        if inst["id"] in done:
            continue
        row = {"id": inst["id"]}
        for name, seed in ORDERS.items():
            t0 = time.time()
            head, lines = shown(inst, seed)
            out = safe_generate(generate, head + MARK + "\n".join(lines))
            row[f"{name}_rank"] = parse(out, inst["candidates"])
            row[f"{name}_raw"] = out[:2000]
            row[f"{name}_sec"] = round(time.time() - t0, 1)
        res.append(row)
        json.dump(res, open(out_path, "w"), indent=1)
        print(inst["id"], {k: v for k, v in row.items() if k.endswith("_sec")},
              [len(row[f"{n}_rank"]) for n in ORDERS], flush=True)
    print("done", len(res), flush=True)


if __name__ == "__main__":
    main()
