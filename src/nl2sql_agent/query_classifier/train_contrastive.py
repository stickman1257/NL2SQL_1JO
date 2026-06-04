import argparse
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score, classification_report


class ProjectionHead(nn.Module):
    def __init__(self, in_dim, hidden_dim, out_dim):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.ReLU(inplace=True),
            nn.Linear(hidden_dim, out_dim),
        )
    def forward(self, x):
        z = self.net(x)
        return F.normalize(z, dim=-1)


class Classifier(nn.Module):
    def __init__(self, in_dim, num_classes=2):
        super().__init__()
        self.fc = nn.Linear(in_dim, num_classes)

    def forward(self, x):
        return self.fc(x)


def supcon_loss(embeddings, labels, temperature=0.1):
    device = embeddings.device
    B = embeddings.size(0)

    sim = embeddings @ embeddings.T / temperature
    sim = sim - sim.max(dim=1, keepdim=True).values.detach()

    labels = labels.view(-1, 1)
    pos_mask = (labels == labels.T).float().to(device)
    self_mask = torch.eye(B, device=device)
    pos_mask = pos_mask - self_mask
    logits_mask = 1.0 - self_mask

    exp_sim = torch.exp(sim) * logits_mask
    log_prob = sim - torch.log(exp_sim.sum(dim=1, keepdim=True) + 1e-12)

    pos_count = pos_mask.sum(dim=1)
    valid = pos_count > 0
    if valid.sum() == 0:
        return torch.tensor(0.0, device=device, requires_grad=True)

    mean_log_prob_pos = (pos_mask * log_prob).sum(dim=1)[valid] / pos_count[valid]
    return -mean_log_prob_pos.mean()


@torch.no_grad()
def evaluate_head(proj, classifier, X, y, device):
    proj.eval()
    classifier.eval()
    z = proj(X.to(device))
    logits = classifier(z)
    probs = F.softmax(logits, dim=-1)[:, 1].cpu().numpy()
    pred = logits.argmax(dim=-1).cpu().numpy()
    y_np = y.numpy()
    acc = accuracy_score(y_np, pred)
    f1 = f1_score(y_np, pred)
    try:
        auroc = roc_auc_score(y_np, probs)
    except ValueError:
        auroc = float("nan")
    return acc, f1, auroc, classification_report(y_np, pred, digits=4)


def evaluate_linear_probe(z_train, y_train, z_val, y_val):
    clf = LogisticRegression(max_iter=2000, class_weight="balanced")
    clf.fit(z_train, y_train)
    pred = clf.predict(z_val)
    proba = clf.predict_proba(z_val)[:, 1]
    acc = accuracy_score(y_val, pred)
    f1 = f1_score(y_val, pred)
    try:
        auroc = roc_auc_score(y_val, proba)
    except ValueError:
        auroc = float("nan")
    return acc, f1, auroc


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features_path", type=str, default="/features/dev_features.pt")
    parser.add_argument("--out_dir", type=str, default="/runs/default")
    parser.add_argument("--proj_dim", type=int, default=128)
    parser.add_argument("--hidden_dim", type=int, default=512)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch_size", type=int, default=128)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--weight_decay", type=float, default=1e-4)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--supcon_weight", type=float, default=0.1)
    parser.add_argument("--val_ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", type=str, default="cuda" if torch.cuda.is_available() else "cpu")
    return parser.parse_args()


def main():
    args = parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    blob = torch.load(args.features_path, map_location="cpu", weights_only=False)
    feats, labels = blob["features"], blob["labels"]

    idx_train, idx_val = train_test_split(
        torch.arange(len(labels)).numpy(),
        test_size=args.val_ratio,
        stratify=labels.numpy(),
        random_state=args.seed,
    )
    X_train, y_train = feats[idx_train], labels[idx_train]
    X_val, y_val = feats[idx_val], labels[idx_val]

    device = args.device
    proj = ProjectionHead(
        in_dim=feats.size(1),
        hidden_dim=args.hidden_dim,
        out_dim=args.proj_dim,
    ).to(device)
    classifier = Classifier(in_dim=args.proj_dim, num_classes=2).to(device)

    counts = torch.bincount(y_train, minlength=2).float()
    class_weight = (counts.sum() / (2.0 * counts)).to(device)
    ce_loss_fn = nn.CrossEntropyLoss(weight=class_weight)

    params = list(proj.parameters()) + list(classifier.parameters())
    optim = torch.optim.AdamW(params, lr=args.lr, weight_decay=args.weight_decay)

    ds = TensorDataset(X_train, y_train)
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=True, drop_last=True)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    best_auroc = -1.0
    for epoch in range(1, args.epochs + 1):
        proj.train(); classifier.train()
        tot_ce, tot_sc, tot, n = 0.0, 0.0, 0.0, 0
        for xb, yb in loader:
            xb, yb = xb.to(device), yb.to(device)

            z = proj(xb)
            logits = classifier(z)

            l_ce = ce_loss_fn(logits, yb)
            l_sc = supcon_loss(z, yb, temperature=args.temperature)
            loss = l_ce + args.supcon_weight * l_sc

            optim.zero_grad()
            loss.backward()
            optim.step()

            bs = xb.size(0)
            tot_ce += l_ce.item() * bs
            tot_sc += l_sc.item() * bs
            tot += loss.item() * bs
            n += bs

        if epoch % 5 == 0 or epoch == args.epochs:
            acc, f1, auroc, report = evaluate_head(proj, classifier, X_val, y_val, device)
            proj.eval()
            with torch.no_grad():
                z_tr = proj(X_train.to(device)).cpu().numpy()
                z_va = proj(X_val.to(device)).cpu().numpy()
            p_acc, p_f1, p_auroc = evaluate_linear_probe(
                z_tr, y_train.numpy(), z_va, y_val.numpy()
            )

            # print(
            #     f"[epoch {epoch:3d}] "
            #     f"ce={tot_ce/n:.4f} supcon={tot_sc/n:.4f} total={tot/n:.4f} | "
            #     f"head: acc={acc:.4f} f1={f1:.4f} auroc={auroc:.4f} | "
            #     f"probe: auroc={p_auroc:.4f}"
            # )

            if auroc > best_auroc:
                best_auroc = auroc
                torch.save({
                    "proj_state_dict": proj.state_dict(),
                    "classifier_state_dict": classifier.state_dict(),
                    "state_dict": proj.state_dict(),
                    "epoch": epoch,
                    "val_acc": acc,
                    "val_f1": f1,
                    "val_auroc": auroc,
                    "val_probe_auroc": p_auroc,
                    "args": vars(args),
                }, out_dir / "best.pt")
                with open(out_dir / "best_report.txt", "w") as f:
                    f.write(
                        f"epoch={epoch} acc={acc:.4f} f1={f1:.4f} "
                        f"auroc={auroc:.4f} probe_auroc={p_auroc:.4f}\n\n{report}"
                    )

    print(f"Best val AUROC (CE head): {best_auroc:.4f}")
    print(f"Artifacts saved to: {out_dir}")


if __name__ == "__main__":
    main()
