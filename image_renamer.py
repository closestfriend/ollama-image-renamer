#!/usr/bin/env python3
"""
image_renamer.py — caption-based image renamer using a local Ollama vision model.

Turns cryptic filenames (Twitter hashes, replicate IDs, sdxl_output_N) into
searchable descriptive slugs, while PRESERVING the original id for recovery.

  new name:  <caption-slug>__src-<original-stem>.<ext>

Default model: qwen3-vl:4b-instruct  (sees images, NO reasoning overhead).
NOTE: use the *-instruct* variant — the bare qwen3-vl tag is the Thinking build
and burns 30-90s/img on hidden reasoning that think:false won't disable (Ollama 0.30.x).

Safe by default: DRY-RUN (prints proposed names, writes a ledger, touches nothing).
Re-run with --apply to actually rename. Resumable: the apply pass reuses the
captions from the dry-run ledger, so no image is captioned twice.

Usage:
  python3 image_renamer.py "<dir>"                 # dry-run
  python3 image_renamer.py "<dir>" --apply         # rename, reusing dry-run captions
  python3 image_renamer.py "<dir>" --limit 20      # first 20 only (quick test)
  python3 image_renamer.py "<dir>" --model qwen3-vl:2b-instruct --maxpx 768
"""
import argparse, base64, json, os, re, subprocess, time, urllib.request, urllib.error

MARKER = "__src-"          # renamed files contain this; we skip them on re-runs (idempotent)
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".heic")
PROMPT = ("Describe this image as a short filename: 4-8 words, lowercase, no punctuation, "
          "naming the main subject concretely. If the image is primarily printed text, read "
          "and quote the first several words verbatim. Reply with ONLY the description.")


def slugify(s, maxlen=60):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower().strip())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:maxlen].strip("-") or "untitled"


def downscale(src, maxpx):
    """Shrink a copy to <=maxpx on the long edge via macOS sips. Never touches the original."""
    out = f"/tmp/_rn_{os.getpid()}.jpg"
    r = subprocess.run(["sips", "-Z", str(maxpx), "-s", "format", "jpeg", src, "--out", out],
                       capture_output=True)
    return out if r.returncode == 0 and os.path.exists(out) else None


def caption(path, model, timeout=180):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    body = {"model": model, "prompt": PROMPT, "images": [b64], "stream": False}
    req = urllib.request.Request("http://localhost:11434/api/generate",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return (json.load(r).get("response") or "").strip()


def unique_name(directory, slug, stem, ext, current):
    base = f"{slug}{MARKER}{slugify(stem, 40)}"
    name = f"{base}{ext}"
    n = 2
    while os.path.exists(os.path.join(directory, name)) and name != current:
        name = f"{base}-{n}{ext}"
        n += 1
    return name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("--model", default="qwen3-vl:4b-instruct")
    ap.add_argument("--maxpx", type=int, default=1024)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    DIR = args.directory
    ledger_path = os.path.join(DIR, ".rename_ledger.jsonl")
    done = {}
    if os.path.exists(ledger_path):
        for line in open(ledger_path):
            try:
                rec = json.loads(line)
                done[rec["original"]] = rec
            except Exception:
                pass

    files = [f for f in sorted(os.listdir(DIR))
             if f.lower().endswith(IMG_EXTS) and MARKER not in f and not f.startswith(".")]
    if args.limit:
        files = files[:args.limit]

    mode = "APPLY (renaming)" if args.apply else "DRY-RUN (no changes)"
    print(f"{mode} | model={args.model} | downscale<= {args.maxpx}px | {len(files)} files")
    print("=" * 80)
    ledger = open(ledger_path, "a")
    t0 = time.time()
    n_ok = n_skip = n_err = n_renamed = 0

    for i, f in enumerate(files, 1):
        stem, ext = os.path.splitext(f)
        ext = ext.lower()
        cached = done.get(f)

        # Resume / reuse: we already have a good caption for this file.
        if cached and cached.get("caption") and not cached.get("error"):
            if not args.apply or cached.get("applied"):
                n_skip += 1
                continue
            # apply pass: rename using the cached dry-run caption (no model call)
            newname = unique_name(DIR, slugify(cached["caption"]), stem, ext, f)
            os.rename(os.path.join(DIR, f), os.path.join(DIR, newname))
            n_renamed += 1
            ledger.write(json.dumps({**cached, "proposed": newname, "applied": True}) + "\n")
            ledger.flush()
            print(f"[{i:3}] RENAMED  {f[:34]:34} -> {newname[:52]}")
            continue

        src = os.path.join(DIR, f)
        ds = downscale(src, args.maxpx)
        used = ds or src
        ts = time.time()
        rec = {"original": f}
        try:
            cap = caption(used, args.model)
            if not cap:
                raise ValueError("empty caption")
            newname = unique_name(DIR, slugify(cap), stem, ext, f)
            rec.update(caption=cap, proposed=newname, applied=False)
            if args.apply:
                os.rename(src, os.path.join(DIR, newname))
                rec["applied"] = True
                n_renamed += 1
            n_ok += 1
            tag = "RENAMED" if args.apply else f"{time.time()-ts:4.1f}s"
            print(f"[{i:3}] {tag:>7}  {f[:34]:34} -> {newname[:52]}")
        except urllib.error.HTTPError as e:
            rec["error"] = f"HTTP {e.code}"
            n_err += 1
            print(f"[{i:3}] !! HTTP {e.code}  {f[:40]} (left as-is)")
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
            n_err += 1
            print(f"[{i:3}] !! {type(e).__name__}  {f[:40]} (left as-is)")
        finally:
            if ds and os.path.exists(ds):
                os.remove(ds)
            ledger.write(json.dumps(rec) + "\n")
            ledger.flush()

    dt = time.time() - t0
    print("=" * 80)
    print(f"captioned {n_ok} | renamed {n_renamed} | skipped {n_skip} | errors {n_err} | {dt:.0f}s")
    if n_ok:
        print(f"avg {dt/n_ok:.1f}s/img  (~{dt/n_ok*605/60:.0f} min for 605)")
    print(f"ledger: {ledger_path}")
    if not args.apply:
        print("DRY-RUN only — review the proposed names above, then re-run with --apply.")


if __name__ == "__main__":
    main()
