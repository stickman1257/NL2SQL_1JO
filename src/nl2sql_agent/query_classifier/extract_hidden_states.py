import argparse
import json
import os
from pathlib import Path
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from tqdm import tqdm


LABEL_MAP = {"simple": 0, "moderate": 1, "challenging": 1}


@torch.no_grad()
def extract_batch(model, tokenizer, texts, layer, pool, device, max_length):
    enc = tokenizer(
        texts,
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=max_length,
    ).to(device)

    outputs = model(**enc, output_hidden_states=True, use_cache=False)
    hs = outputs.hidden_states[layer]

    attn = enc["attention_mask"]

    # Last token pooling
    batch_idx = torch.arange(hs.size(0), device=hs.device)
    if tokenizer.padding_side == "left":
        last_vec = hs[:, -1, :]
    else:
        last_idx = attn.sum(dim=1) - 1
        last_vec = hs[batch_idx, last_idx, :]

    # Mean pooling
    mask = attn.unsqueeze(-1).to(hs.dtype)
    mean_vec = (hs * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-6)

    if pool == "last":
        pooled = last_vec
    elif pool == "mean":
        pooled = mean_vec
    elif pool == "hybrid":
        pooled = 0.5 * (last_vec + mean_vec)
    else:
        raise ValueError(f"Unknown pool type: {pool}")

    return pooled.cpu()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_path", type=str, default="/BIRD-SQL/dev.json")
    parser.add_argument("--model_name", type=str, default="Qwen/Qwen2.5-1.5B-Instruct")
    parser.add_argument("--layer", type=int, default=16)
    parser.add_argument("--pool", type=str, default="mean", choices=["last", "mean", "hybrid"])
    parser.add_argument("--out_path", type=str, default="/features/dev_features.pt")
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--max_length", type=int, default=512)
    parser.add_argument("--device", type=str, default="cuda" if torch.cuda.is_available() else "cpu")
    return parser.parse_args()


def main():
    args = parse_args()

    with open(args.data_path, "r") as f:
        data = json.load(f)

    questions = [d["question"] for d in data]
    labels = [LABEL_MAP[d["difficulty"]] for d in data]

    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"

    model = AutoModelForCausalLM.from_pretrained(
        args.model_name,
        torch_dtype=torch.float16 if "cuda" in args.device else torch.float32,
        ).to(args.device)
    
    model.eval()

    feats = []
    for i in tqdm(range(0, len(questions), args.batch_size)):
        batch = questions[i : i + args.batch_size]
        feats.append(extract_batch(
            model, tokenizer, batch,
            layer=args.layer, pool=args.pool,
            device=args.device, max_length=args.max_length,
        ))
    feats = torch.cat(feats, dim=0).float()
    labels_t = torch.tensor(labels, dtype=torch.long)

    Path(args.out_path).parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "features": feats,
        "labels": labels_t,
        "meta": {
            "model_name": args.model_name,
            "layer": args.layer,
            "pool": args.pool,
            "data_path": args.data_path,
        },
    }, args.out_path)


if __name__ == "__main__":
    main()
