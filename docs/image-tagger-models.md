# Image Tagger Model Alternatives

This document summarizes current image tagger options for Upvote Monitor's 2D illustration workflow. The goal is to choose models that can run locally on self-hosted systems, generate useful tags, and support an `illustration_score` for auto-approval rules.

## Requirements

- Self-hostable inference, preferably with ONNX Runtime.
- Good performance on anime, manga, western illustration, and booru-style images.
- Useful structured tags for later filtering, routing, and export.
- Reasonable CPU/RAM requirements for home servers.
- Clear enough licensing for a distributed self-hosted app.

## Summary

`SmilingWolf/wd-swinv2-tagger-v3` is still the safest default. It is Apache-2.0, ONNX-compatible, widely used, and small enough to plausibly run in a background queue on modest hardware.

Within SmilingWolf's current WD v3 ONNX-compatible family, the best published validation scores are EVA02-Large, ViT-Large, then SwinV2. The v1.4/v2 models use older Danbooru coverage and their published F1 numbers are not directly comparable to v3 because the v3 cards switched to Macro-F1.

The most interesting newer alternative is `pixai-labs/pixai-tagger-v0.9`, especially through the `deepghs/pixai-tagger-v0.9-onnx` export. It has newer Danbooru coverage and stronger character/tag recall, but it is significantly heavier.

`Camais03/camie-tagger-v2` is technically compelling. `fancyfeast/joytag` is lightweight enough to benchmark. `lodestones/taggerine` is powerful but too large for the default self-hosted path.

## Candidate Models

| Model | License | Runtime / Files | Size / Cost | Notes | Fit |
| --- | --- | --- | --- | --- | --- |
| [`SmilingWolf/wd-swinv2-tagger-v3`](https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3) | Apache-2.0 | ONNX, safetensors, `timm` | 98M params | Supports ratings, characters, and general tags. Trained on Danbooru through 2024-02. Requires `onnxruntime >= 1.17.0`. | Best default |
| [`SmilingWolf/wd-eva02-large-tagger-v3`](https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3) | Apache-2.0 | ONNX, safetensors, `timm` | ~0.3B params | Strongest published WD v3 validation score, but much heavier than SwinV2. | Best quality mode |
| [`SmilingWolf/wd-vit-large-tagger-v3`](https://huggingface.co/SmilingWolf/wd-vit-large-tagger-v3) | Apache-2.0 | ONNX, safetensors, `timm` | ~0.3B params | Second-best published WD v3 validation score. Similar file size to EVA02-Large. | Alternate quality mode |
| [`pixai-labs/pixai-tagger-v0.9`](https://huggingface.co/pixai-labs/pixai-tagger-v0.9) | Apache-2.0 | PyTorch checkpoint, gated base repo | ~1.27 GB checkpoint | Newer Danbooru snapshot, about 13.5k tags, recall-oriented, strong character coverage. | High-quality candidate |
| [`deepghs/pixai-tagger-v0.9-onnx`](https://huggingface.co/deepghs/pixai-tagger-v0.9-onnx) | Apache-2.0 | ONNX | 317.9M params, 448x448 input | ONNX export of PixAI Tagger. Includes 9,741 general tags and 3,720 character tags. Recommended thresholds: general `0.3`, character `0.85`. | Best PixAI route |
| [`Camais03/camie-tagger-v2`](https://huggingface.co/Camais03/camie-tagger-v2) | GPL-3.0 | ONNX, safetensors | 143M params reported | 70,527 possible tags, trained on Danbooru 2024 data, strong reported character/copyright/rating performance. | Benchmark only (GPL license is acceptable) |
| [`fancyfeast/joytag`](https://huggingface.co/fancyfeast/joytag) | Apache-2.0 | ONNX, safetensors, Transformers | 91.5M params | Sparse model card, but lightweight and Danbooru-style tags are available through `top_tags.txt`. | Lightweight alternative |
| [`lodestones/taggerine`](https://huggingface.co/lodestones/taggerine) | Apache-2.0 | safetensors, PyTorch | ~5.3 GB weights; ~632M backbone + ~480M head params | DINOv3 ViT-H/16+ booru tagger with 74,625 tags from Danbooru and e621. CPU mode exists but will be slow. | Power-user only |
| [`oovm/deep-danbooru`](https://huggingface.co/oovm/deep-danbooru) and other DeepDanbooru ports | Varies | ONNX variants exist | Older | Useful as a legacy baseline, but less attractive than WD v3 or newer taggers. | Legacy fallback |

## Recommendation

Use a pluggable tagger backend with this default order:

1. Default: `SmilingWolf/wd-swinv2-tagger-v3`
2. Optional high-quality WD-compatible profile: `SmilingWolf/wd-eva02-large-tagger-v3`
3. Optional alternate high-quality WD-compatible profile: `SmilingWolf/wd-vit-large-tagger-v3`
4. Optional high-quality backend: `deepghs/pixai-tagger-v0.9-onnx`
5. Experimental backends: `fancyfeast/joytag`, `Camais03/camie-tagger-v2`
6. Power-user backend: `lodestones/taggerine`
7. Legacy fallback: DeepDanbooru ONNX ports

The app should store the selected model name/version with every analysis result. This matters because tag scores are not comparable across models.

Implemented WD-compatible profiles:

- `SmilingWolf/wd-swinv2-tagger-v3`
- `SmilingWolf/wd-eva02-large-tagger-v3`
- `SmilingWolf/wd-vit-large-tagger-v3`

Deprecated built-in profile:

- `SmilingWolf/wd-v1-4-vit-tagger-v2`

The current WD backend expects Hugging Face repos with `model.onnx` and `selected_tags.csv` using WD-style tag categories. PixAI, Camie, JoyTag, Taggerine, and DeepDanbooru entries require separate backend adapters rather than only new profile rows.

## Product Implications

`SmilingWolf/wd-swinv2-tagger-v3` should be enough for the first implementation of:

- 2D illustration auto-approval.
- Tag display in the review UI.
- Tag-based filtering later.
- Routing hints for reverse image search.

PixAI should be benchmarked soon after because it may improve character and long-tail tag coverage. It is probably better for search and curation, but its recall-first behavior may generate more false positives unless thresholds are tuned.

Camie may be useful for experiments because of its very large vocabulary and strong reported category scores.

Taggerine should not be a default. It is impressive, but its weight file and parameter count are too large for the target home-server audience.

## Benchmark Plan

Before finalizing backends, run a small local benchmark:

- 200-500 representative images from Reddit/X likes.
- Include illustrations, manga, screenshots, photos, memes, 3D renders, cosplay, and noisy reposts.
- Measure CPU inference time, peak RAM, model download size, and startup/load time.
- Compare tag usefulness, `illustration_score` quality, false auto-approvals, and false queues.
- Keep thresholds conservative: auto-approve only when the model and scoring layer agree strongly.

Suggested acceptance target for the default backend:

- Fast enough for background queue use on CPU.
- Very low false auto-approval rate for non-illustrations.
- Good enough tag quality to explain why an item was approved.
- No network dependency after model files are downloaded.

## Implementation Notes

The backend should not hard-code WD-specific assumptions into the database schema. Store normalized analysis output:

```json
{
  "model": "SmilingWolf/wd-swinv2-tagger-v3",
  "model_version": "v3",
  "illustration_score": 0.94,
  "ratings": {
    "general": 0.91,
    "sensitive": 0.04,
    "questionable": 0.03,
    "explicit": 0.02
  },
  "tags": {
    "1girl": 0.93,
    "solo": 0.88,
    "long_hair": 0.72
  }
}
```

Keep raw tag probabilities for future recalibration. The first scoring layer can be heuristic, but user approvals should eventually become calibration data.

## Sources

- [`SmilingWolf/wd-swinv2-tagger-v3`](https://huggingface.co/SmilingWolf/wd-swinv2-tagger-v3)
- [`SmilingWolf/wd-eva02-large-tagger-v3`](https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3)
- [`SmilingWolf/wd-vit-large-tagger-v3`](https://huggingface.co/SmilingWolf/wd-vit-large-tagger-v3)
- [`pixai-labs/pixai-tagger-v0.9`](https://huggingface.co/pixai-labs/pixai-tagger-v0.9)
- [`deepghs/pixai-tagger-v0.9-onnx`](https://huggingface.co/deepghs/pixai-tagger-v0.9-onnx)
- [`Camais03/camie-tagger-v2`](https://huggingface.co/Camais03/camie-tagger-v2)
- [`fancyfeast/joytag`](https://huggingface.co/fancyfeast/joytag)
- [`lodestones/taggerine`](https://huggingface.co/lodestones/taggerine)
- [`oovm/deep-danbooru`](https://huggingface.co/oovm/deep-danbooru)
- [Recognize Anything Model](https://recognize-anything.github.io/)
