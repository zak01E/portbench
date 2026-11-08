"""Fine-tune Gemma 4 E2B (QLoRA) to re-rank the learned ranker's shortlist, with project-level cross-validation.

Same folds as learn_rank.py (seed 0): every project is re-ranked by an adapter that never saw it in training.
Per training instance the prompt is the re-ranking prompt of gemma_rerank.py with the 30 shortlisted files shown in
2 random orders, and the target is the gold files of the shortlist in the order shown. Training instances without a
gold file in their shortlist are skipped. The loss covers only the answer tokens; logits are computed for those
positions only (the vocabulary has 262k entries).
Also runs the zero-shot model on the same prompts, so the effect of training is measured on identical inputs.
Usage: python gemma_lora.py rerank_inputs.json <gemma-4-e2b-it dir>
Output: gemma_e2b_lora.json (per instance: fold, zero-shot and fine-tuned answers) and training losses.
"""
import json, math, os, random, re, sys, time

import torch
from transformers import AutoProcessor, AutoModelForCausalLM, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model

INPUT, MODEL = sys.argv[1], sys.argv[2]
OUT = os.environ.get("GEMMA_OUT", "gemma_e2b_lora.json")
EPOCHS, LR, ACCUM, PERMS, RANK = 2, 2e-4, 4, 2, 16

ASK = ("You are porting the C/C++ project {repo} from Linux to QNX 8.0 (POSIX; compiler macro __QNX__; "
       "CMake sets CMAKE_SYSTEM_NAME=QNX; networking is in libsocket; no Linux-only APIs such as epoll, "
       "inotify, prctl or /proc). A ranking tool shortlisted the files below, best first, with their "
       "#include lines and platform-specific lines. List the files that most likely need changes for this "
       "port, most likely first, one path per line, copied exactly. Output only paths.\n\n")


def prompt(inst, order):
    text = ASK.format(repo=inst["repo"])
    for i, f in enumerate(order, 1):
        text += f"## {i}. {f}\n" + "\n".join(inst["excerpts"][f]) + "\n"
    return text


def parse(out, numbered):
    cset, got = set(numbered), []
    for line in out.split("\n"):
        s = line.strip().strip("`*-• #").strip()
        if re.fullmatch(r"\d+[.)]?", s):
            i = int(re.match(r"\d+", s).group()) - 1
            p = numbered[i] if 0 <= i < len(numbered) else ""
        else:
            p = re.sub(r"^\d+[.)]\s+", "", s).split(" ")[0].strip("`*")
        if p in cset and p not in got:
            got.append(p)
    return got


def main():
    data = json.load(open(INPUT))
    ids = sorted(d["id"] for d in data)
    random.Random(0).shuffle(ids)
    fold = {iid: i % 5 for i, iid in enumerate(ids)}  # same assignment as learn_rank.py, seed 0

    proc = AutoProcessor.from_pretrained(MODEL)
    tok = proc.tokenizer if hasattr(proc, "tokenizer") else proc
    q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16)
    base = AutoModelForCausalLM.from_pretrained(MODEL, quantization_config=q, device_map={"": 0})
    # no prepare_model_for_kbit_training: it casts the large per-layer embedding tables to fp32
    base.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    base.enable_input_require_grads()
    cap = getattr(base.config.get_text_config(), "final_logit_softcapping", None)
    eos = base.generation_config.eos_token_id
    eos = set(eos if isinstance(eos, (list, tuple)) else [eos])
    end = next((i for t in ("<end_of_turn>", "<turn|>", "<eos>") for i in [tok.convert_tokens_to_ids(t)]
                if i in eos), max(eos))
    print("end-of-answer token", end, tok.convert_ids_to_tokens(end), flush=True)
    names = sorted({n.split(".")[-1] for n, _ in base.named_modules()})
    targets = [n for n, m in base.named_modules()
               if n.split(".")[-1] in ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")
               and "language_model" in n and isinstance(m, torch.nn.Module)]
    print("LoRA target modules:", len(targets), targets[:3], flush=True)
    assert targets, names[:50]
    cfg = LoraConfig(r=RANK, lora_alpha=2 * RANK, lora_dropout=0.05, target_modules=targets, task_type="CAUSAL_LM")

    def encode(text, answer=None):
        msgs = [{"role": "user", "content": [{"type": "text", "text": text}]}]
        p = proc.apply_chat_template(msgs, add_generation_prompt=True, tokenize=True, return_tensors="pt",
                                     return_dict=True, enable_thinking=False)
        ids_p = p["input_ids"][0]
        if answer is None:
            return ids_p, None
        a = torch.tensor(tok(answer, add_special_tokens=False)["input_ids"] + [end])
        return torch.cat([ids_p, a]), len(ids_p)

    def head(m):
        b = m.get_base_model() if hasattr(m, "get_base_model") else m
        return b.model, b.lm_head

    def generate(m, text):
        dec, lm = head(m)
        ids_p, _ = encode(text)
        ids_p = ids_p.unsqueeze(0).to("cuda:0")
        n, out, got = ids_p.shape[1], None, []
        with torch.no_grad():
            for s0 in range(0, n, 2048):
                e = min(n, s0 + 2048)
                out = dec(input_ids=ids_p[:, s0:e], attention_mask=torch.ones(1, e, dtype=torch.long, device="cuda:0"),
                          past_key_values=out.past_key_values if out is not None else None, use_cache=True)
            length = n
            for _ in range(350):
                nxt = lm(out.last_hidden_state[:, -1:])[:, -1].argmax(-1, keepdim=True)
                if nxt.item() in eos:
                    break
                got.append(nxt.item()); length += 1
                out = dec(input_ids=nxt, attention_mask=torch.ones(1, length, dtype=torch.long, device="cuda:0"),
                          past_key_values=out.past_key_values, use_cache=True)
        return tok.decode(got, skip_special_tokens=True)

    res = {d["id"]: {"id": d["id"], "fold": fold[d["id"]]} for d in data}
    # zero-shot on the same prompts
    base.eval()
    for d in data:
        t0 = time.time()
        raw = generate(base, prompt(d, d["shortlist"]))
        res[d["id"]].update({"zero_raw": raw[:2000], "zero_rank": parse(raw, d["shortlist"]),
                             "zero_sec": round(time.time() - t0, 1)})
    print("zero-shot done", flush=True)
    json.dump(list(res.values()), open(OUT, "w"), indent=1)

    model, losses = None, {}
    for k in range(5):
        model = get_peft_model(base if model is None else model.unload(), cfg)
        model.print_trainable_parameters()
        rnd = random.Random(k)
        examples = []
        for d in data:
            if fold[d["id"]] == k:
                continue
            gold = set(d["gold"]) & set(d["shortlist"])
            if not gold:
                continue
            for _ in range(PERMS):
                order = d["shortlist"][:]; rnd.shuffle(order)
                examples.append((prompt(d, order), "\n".join(f for f in order if f in gold)))
        opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=LR, weight_decay=0.0)
        total = EPOCHS * math.ceil(len(examples) / ACCUM)
        sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / 5) * max(0.0, 1 - s / total))
        model.train(); dec, lm = head(model); step = 0; losses[k] = []
        for ep in range(EPOCHS):
            rnd.shuffle(examples)
            for i, (text, ans) in enumerate(examples):
                ids_full, npr = encode(text, ans)
                ids_full = ids_full.unsqueeze(0).to("cuda:0")
                h = dec(input_ids=ids_full, attention_mask=torch.ones_like(ids_full), use_cache=False).last_hidden_state
                logits = lm(h[:, npr - 1:-1]).float()  # positions that predict the answer tokens
                if cap:
                    logits = torch.tanh(logits / cap) * cap
                loss = torch.nn.functional.cross_entropy(logits[0], ids_full[0, npr:]) / ACCUM
                loss.backward()
                losses[k].append(round(loss.item() * ACCUM, 4))
                if (i + 1) % ACCUM == 0 or i == len(examples) - 1:
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    opt.step(); sched.step(); opt.zero_grad(); step += 1
            print(f"fold {k} epoch {ep} examples {len(examples)} mean loss "
                  f"{sum(losses[k][-len(examples):]) / len(examples):.3f}", flush=True)
        model.eval()
        for d in data:
            if fold[d["id"]] != k:
                continue
            t0 = time.time()
            raw = generate(model, prompt(d, d["shortlist"]))
            res[d["id"]].update({"ft_raw": raw[:2000], "ft_rank": parse(raw, d["shortlist"]),
                                 "ft_sec": round(time.time() - t0, 1)})
            print(d["id"], len(res[d["id"]]["ft_rank"]), flush=True)
        json.dump(list(res.values()), open(OUT, "w"), indent=1)
        json.dump(losses, open(OUT.replace(".json", "_losses.json"), "w"))
        torch.cuda.empty_cache()
    print("done", flush=True)


if __name__ == "__main__":
    main()
