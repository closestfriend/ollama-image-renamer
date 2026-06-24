# ollama-image-renamer

Batch-rename images by what's *in* them, using a local [Ollama](https://ollama.com)
vision model. Turns cryptic filenames — Twitter hashes, `replicate-prediction-*`,
`sdxl_output_7.jpeg`, `IMG_1052.JPG` — into searchable descriptive slugs, while
**preserving the original id** so nothing is lost:

```
Gh1OX0xWwAA7ReS.jpeg          ->  red-dripping-anarchist-symbol__src-gh1ox0xwwaa7res.jpeg
replicate-prediction-w5r27.jpg ->  gentle-collapse-johnny-tucker-book-cover__src-replicate-prediction-w5r27.jpg
s-l1600.jpg                    ->  mind-amp-second-edition-by-michael-a-aquino__src-s-l1600.jpg
```

Fully local. No cloud, no API keys, no images leave your machine.

## Why it exists

A folder of hundreds of images with meaningless filenames is invisible to search.
Captioning each one locally makes the whole pile greppable / Spotlight-able again.

## Usage

```bash
# 1. dry-run: proposes names, writes a ledger, changes NOTHING
python3 image_renamer.py "/path/to/folder"

# 2. review the proposed names, then apply (reuses the dry-run captions — instant)
python3 image_renamer.py "/path/to/folder" --apply

# options
python3 image_renamer.py "/path/to/folder" --limit 20            # quick test on first 20
python3 image_renamer.py "/path/to/folder" --model qwen3-vl:2b-instruct --maxpx 768
```

### Design

- **Safe by default** — dry-run unless you pass `--apply`. Never overwrites; resolves
  collisions; on `--apply` it reuses captions from the dry-run ledger so no image is
  captioned twice.
- **Resumable** — every result is appended to `.rename_ledger.jsonl` in the target
  folder. Re-running skips finished files.
- **Robust** — undecodable images (corrupt / mislabeled formats) are logged and left
  untouched; one bad file never aborts the batch.
- **Fast enough** — downscales a temp copy to `--maxpx` (default 1024) via macOS `sips`
  before inference. Originals are never modified. ~15s/image on an M-series Mac with
  `qwen3-vl:4b-instruct` (≈2.5 hrs for 600 images).
- **Idempotent** — renamed files contain the `__src-` marker and are skipped on re-runs.

## Requirements

- macOS (uses the built-in `sips` for downscaling) + Python 3
- [Ollama](https://ollama.com) running locally, with a vision model pulled:
  ```bash
  ollama pull qwen3-vl:4b-instruct
  ```

## Choosing a model — hard-won notes

These came out of actually benchmarking, June 2026, Ollama 0.30.9:

- **Use the `-instruct` variant, not the bare tag.** `qwen3-vl:4b` is the *Thinking*
  build — it burns 30–90s/image generating hidden reasoning before a one-line caption,
  and `think:false` / `/no_think` do **not** disable it in this Ollama version.
  `qwen3-vl:4b-instruct` has no reasoning capability at all → same vision quality,
  a fraction of the time.
- **Avoid the `-mlx` builds for vision.** As of this writing, Ollama's MLX runner
  accelerates *text* but silently **drops image input** — the model loads, runs blazing
  fast, and hallucinates captions unrelated to the image (it never sees it). Vision still
  runs through the GGUF/llama.cpp engine. The `vision` capability tag reflects the
  *model*, not the MLX *runner*.
- **Resolution is the speed lever** once reasoning is off — downscaling the input is what
  takes a non-thinking model from variable 15–90s down to a steady ~15s. (With a thinking
  model, downscaling does nothing because reasoning dominates the time.)

Other capable local vision models worth trying: `qwen3-vl:2b-instruct` (faster),
`minicpm-v`, `gemma` vision builds, `moondream`.

## License

MIT
