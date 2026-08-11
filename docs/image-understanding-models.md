# Image Understanding Model Alternatives

Last reviewed: 2026-06-22

This document summarizes model options for deciding whether an image is a 2D illustration, while keeping useful room for broader media such as cosplay, screenshots, photos, 3D renders, manga pages, memes, and reposts.

This is a companion to [`image-tagger-models.md`](./image-tagger-models.md). The tagger document focuses on Danbooru-style tag outputs. This document focuses on CLIP-like embedding models, visual classifiers, captioning models, and small vision-language models that can add medium-aware signals.

## Requirements

- Self-hostable inference.
- Small enough for a home server, ideally CPU-capable for background jobs.
- GPU-friendly options are acceptable for higher-quality or uncertain-case analysis.
- Useful for anime and non-anime 2D illustration.
- Able to distinguish 2D illustration from adjacent media such as cosplay photos, screenshots, 3D renders, manga pages, and memes.
- Stable outputs that can be stored with the model name and version for future recalibration.

## Summary

The best path is probably not to replace the existing Danbooru-style taggers. Instead, add a second visual-understanding layer:

1. Keep Danbooru-style tags for organization, filtering, explainability, and user-facing metadata.
2. Add an embedding or classifier backend for `illustration_score` and broader medium detection.
3. Add an optional captioning or VLM backend for uncertain cases, richer descriptions, and future search features.

For the first benchmark, prioritize `SigLIP 2`, `MobileCLIP2`, `OpenCLIP`, and `DINOv2`. These should be more reliable for medium classification than asking Danbooru tags alone to separate illustration, cosplay, photo, screenshot, and 3D render cases.

Captioning models are still useful, but generated captions are lossy and not naturally calibrated. They should be treated as sidecar evidence rather than the only source of truth for auto-approval.

## Model Categories

### Embedding And Classifier Models

These models produce image embeddings or image-text scores. They are the strongest candidates for the app's `illustration_score` because they can feed a small local classifier.

| Model family | Runtime / ecosystem | Size / cost | Notes | Fit |
| --- | --- | --- | --- | --- |
| [`google/siglip2-base-patch16-224`](https://huggingface.co/google/siglip2-base-patch16-224) and other SigLIP 2 variants | Transformers / image-text embedding | Varies by checkpoint | Modern CLIP-like model family. Good for zero-shot prompts and trained classifiers over embeddings. | Best first CLIP-like benchmark |
| [MobileCLIP / MobileCLIP2](https://github.com/apple/ml-mobileclip) | PyTorch ecosystem; designed for efficient inference | Small mobile-oriented variants | Built for low-latency image-text embedding. Attractive for background jobs on modest systems. | Best efficiency candidate |
| [OpenCLIP](https://github.com/mlfoundations/open_clip) checkpoints | Mature PyTorch ecosystem | Varies from small ViT-B to larger ViT-L/H models | Broad ecosystem with many pretrained models. Useful baseline because it is easy to benchmark and swap checkpoints. | Baseline and compatibility candidate |
| [`facebook/dinov2-base`](https://huggingface.co/facebook/dinov2-base) and smaller/larger DINOv2 variants | Transformers / visual embeddings | `dinov2-base` is 86.6M params | Not text-aligned, but excellent visual features. Needs a trained classifier head instead of zero-shot text prompts. | Strong if local labels are available |

Recommended use:

- Store embeddings or derived classifier scores, not only the final boolean decision.
- Train a small model on user-labeled examples after enough approvals/rejections exist.
- Keep zero-shot prompt scores as a bootstrap path, not the final calibration strategy.

Example output shape:

```json
{
  "model": "google/siglip2-base-patch16-224",
  "model_version": "literal-commit-sha",
  "model_revision": "literal-commit-sha",
  "model_sha256": "sha256-of-model-file",
  "preprocessing_version": "named-preprocessing-contract",
  "scores": {
    "2d_illustration": 0.91,
    "anime_illustration": 0.82,
    "western_illustration": 0.37,
    "manga_page": 0.24,
    "photo": 0.05,
    "cosplay_photo": 0.03,
    "3d_render": 0.18,
    "screenshot": 0.12,
    "meme": 0.08
  }
}
```

### Small Captioning And VLM Models

These models generate captions or answer visual questions. They can improve review UX and uncertain-case handling, but they should not be the only source for auto-approval.

| Model | Runtime / ecosystem | Size / cost | Notes | Fit |
| --- | --- | --- | --- | --- |
| [`microsoft/Florence-2-base`](https://huggingface.co/microsoft/Florence-2-base) / [`microsoft/Florence-2-large`](https://huggingface.co/microsoft/Florence-2-large) | Transformers | Base is about 0.23B params; large is about 0.77B params | General vision foundation model for captioning, detailed captioning, OCR, detection, and grounding. | Best general small captioning baseline |
| [`MiaoshouAI/Florence-2-base-PromptGen-v2.0`](https://huggingface.co/MiaoshouAI/Florence-2-base-PromptGen-v2.0) / [`MiaoshouAI/Florence-2-large-PromptGen-v2.0`](https://huggingface.co/MiaoshouAI/Florence-2-large-PromptGen-v2.0) | Transformers | Base and large Florence-2-derived variants | Prompt/caption generation finetune with modes for tags, detailed captions, mixed captions, and composition analysis. Especially relevant for illustration workflows. | Best captioning sidecar candidate |
| [`HuggingFaceTB/SmolVLM-256M-Instruct`](https://huggingface.co/HuggingFaceTB/SmolVLM-256M-Instruct) | Transformers | 256M params | Very small VLM. Good candidate for local captioning and visual question answering with low resource usage. | Best tiny VLM candidate |
| [`HuggingFaceTB/SmolVLM2-500M-Video-Instruct`](https://huggingface.co/HuggingFaceTB/SmolVLM2-500M-Video-Instruct) | Transformers | 500M params | Small image/video-capable VLM. Useful if future workflows include short videos or animated media. | Small broad-media candidate |
| [`vikhyatk/moondream2`](https://huggingface.co/vikhyatk/moondream2) | Transformers / custom examples | 2B class | Compact general VLM with captioning, querying, detection, pointing, and open-vocabulary tagging. | Higher-quality local VLM probe |
| [`OpenGVLab/InternVL3-1B`](https://huggingface.co/OpenGVLab/InternVL3-1B) | Transformers | 1B class | General multimodal model with relatively small size compared with 3B+ VLMs. | Middle tier VLM candidate |

Recommended use:

- Run only after the fast tagger/classifier layer is uncertain.
- Store the prompt, model name, model revision, generated text, and any parsed labels.
- Avoid treating free-form captions as calibrated probabilities.

Example output shape:

```json
{
  "model": "MiaoshouAI/Florence-2-base-PromptGen-v2.0",
  "model_version": "literal-commit-sha",
  "model_revision": "literal-commit-sha",
  "model_sha256": "sha256-of-model-file",
  "preprocessing_version": "named-preprocessing-contract",
  "prompt": "<MORE_DETAILED_CAPTION>",
  "caption": "A digital anime-style illustration of a character standing in a city street at night.",
  "parsed_medium_hints": {
    "2d_illustration": true,
    "anime": true,
    "photo": false,
    "cosplay": false
  }
}
```

### Larger Broad-Media Models

These are probably too heavy for default background inference, but they may be useful as optional quality modes for users with GPUs or for difficult edge cases.

| Model | Runtime / ecosystem | Size / cost | Notes | Fit |
| --- | --- | --- | --- | --- |
| [`Qwen/Qwen2.5-VL-3B-Instruct`](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct) | Transformers / Qwen tooling | 3B class | Strong general VLM for object recognition, text/layout understanding, structured outputs, localization, and broad media understanding. | Best larger broad-media candidate |
| [`google/paligemma2-3b-mix-224`](https://huggingface.co/google/paligemma2-3b-mix-224) | Transformers | 3B class | General captioning, VQA, OCR, and detection model based on SigLIP plus Gemma 2. Check Gemma license terms before distribution. | Fine-tuning and research candidate |
| [`fancyfeast/llama-joycaption-beta-one-hf-llava`](https://huggingface.co/fancyfeast/llama-joycaption-beta-one-hf-llava) | Transformers / LLaVA-style | 8B class | Built for rich image captioning across digital art, photoreal images, anime, furry, SFW, and NSFW material. License and resource cost make it unsuitable as a default. | Power-user caption quality mode |

Recommended use:

- Keep these out of the default install path.
- Run only on GPU or as an opt-in queued job.
- Use structured prompts that force explicit medium labels instead of relying only on prose.

Example prompt:

```text
Classify the visual medium of this image. Return JSON with booleans and short evidence for:
2d_illustration, anime, western_illustration, manga_page, photo, cosplay_photo,
3d_render, screenshot, meme, unknown.
```

### General Tagging Models

These are not Danbooru taggers, but they may detect broad real-world objects and contexts that anime-focused taggers miss.

| Model | Runtime / ecosystem | Size / cost | Notes | Fit |
| --- | --- | --- | --- | --- |
| [`xinyu1205/recognize-anything-plus-model`](https://huggingface.co/xinyu1205/recognize-anything-plus-model) / [RAM++ project](https://recognize-anything.github.io/) | PyTorch ecosystem | Larger than the smallest embedding models | Open-vocabulary/general image tagging. Useful for real-world cues such as person, costume, stage, camera, food, vehicle, room, sign, and screen. | Optional broad-context tagger |

Recommended use:

- Treat RAM++ as broad context, not a replacement for Danbooru tags.
- Use it to reduce false approvals on photos, cosplay, screenshots, and real-world scenes.

## Recommended Architecture

Use a layered pipeline:

1. Run the selected Danbooru-style tagger from [`image-tagger-models.md`](./image-tagger-models.md).
2. Run a lightweight visual embedding or classifier backend.
3. Fuse the two outputs into `illustration_score`.
4. Run an optional captioning or VLM backend only for uncertain cases or richer metadata.

The first production version can use heuristic fusion:

```json
{
  "tagger": {
    "model": "SmilingWolf/wd-swinv2-tagger-v3",
    "illustration_score": 0.86,
    "tags": {
      "1girl": 0.93,
      "solo": 0.88,
      "long_hair": 0.72
    }
  },
  "medium_classifier": {
    "model": "google/siglip2-base-patch16-224",
    "scores": {
      "2d_illustration": 0.91,
      "photo": 0.05,
      "cosplay_photo": 0.03,
      "3d_render": 0.18,
      "screenshot": 0.12
    }
  },
  "final": {
    "illustration_score": 0.93,
    "decision": "auto_approve",
    "reason_codes": [
      "tagger_high_illustration_confidence",
      "medium_classifier_prefers_2d_illustration",
      "photo_and_cosplay_scores_low"
    ]
  }
}
```

Later, replace the heuristic with a calibrated classifier trained from local user approvals and corrections.

## Benchmark Plan

Use the same representative image set for every candidate:

- 200-500 images from the actual ingestion sources.
- Include anime illustrations, western illustrations, manga pages, comics, screenshots, memes, photos, cosplay, 3D renders, product images, food, landscapes, UI screenshots, and noisy reposts.
- Label at least these fields: `2d_illustration`, `anime`, `western_illustration`, `manga_page`, `photo`, `cosplay_photo`, `3d_render`, `screenshot`, `meme`, `unknown`.
- Measure CPU inference time, GPU inference time if available, peak RAM/VRAM, model download size, startup time, and batch throughput.
- Track false auto-approvals separately from false queues. False auto-approvals are more expensive.

Suggested benchmark order:

1. Current Danbooru tag heuristic.
2. Danbooru tag confidence classifier.
3. SigLIP 2 zero-shot prompt scores.
4. MobileCLIP2 zero-shot prompt scores.
5. DINOv2 embeddings plus a small trained classifier.
6. Fusion of Danbooru tags plus the best embedding/classifier model.
7. Optional captioning/VLM review for uncertain cases.

Suggested acceptance criteria for the default backend:

- Fast enough for background queue use on CPU.
- Very low false auto-approval rate for non-illustrations.
- Good enough confidence explanations for the review UI.
- No network dependency after model files are downloaded.
- Model name, revision, preprocessing, thresholds, and score schema are stored with every result.

## Implementation Notes

Do not hard-code a single model family into the database schema. Store normalized analysis output with separate sections for tags, medium classifier scores, captions, and final decisions.

Minimum fields for every model output:

- `model`
- `model_revision`
- `model_sha256`
- `backend`
- `preprocessing`
- `created_at`
- `scores` or `raw_output`
- `thresholds`

For embedding models, either store the embedding vector or store enough metadata to reproduce it. If embeddings are stored, include the vector dimension and normalization method.

For captioning models, store the prompt template. The same image can produce different captions under different prompts.

For classifiers trained on local labels, store:

- Base embedding model.
- Training data version.
- Label schema version.
- Classifier type.
- Calibration method.
- Thresholds used for auto-approval and review queue routing.


## Current Recommendation

Implement a pluggable `medium_classifier` backend before adding a large captioning dependency.

Recommended first candidates:

1. `google/siglip2-base-patch16-224`
2. MobileCLIP2 small checkpoint
3. OpenCLIP ViT-B or ViT-L checkpoint
4. `facebook/dinov2-base` with a small trained classifier

Recommended captioning sidecar candidates:

1. `MiaoshouAI/Florence-2-base-PromptGen-v2.0`
2. `microsoft/Florence-2-base`
3. `HuggingFaceTB/SmolVLM-256M-Instruct`
4. `HuggingFaceTB/SmolVLM2-500M-Video-Instruct`

Recommended broad-media quality candidates:

1. `Qwen/Qwen2.5-VL-3B-Instruct`
2. `OpenGVLab/InternVL3-1B`
3. `vikhyatk/moondream2`
4. `fancyfeast/llama-joycaption-beta-one-hf-llava`

## Sources

- [CLIP paper](https://arxiv.org/abs/2103.00020)
- [SigLIP 2 paper](https://arxiv.org/abs/2502.14786)
- [`google/siglip2-base-patch16-224`](https://huggingface.co/google/siglip2-base-patch16-224)
- [MobileCLIP / MobileCLIP2](https://github.com/apple/ml-mobileclip)
- [OpenCLIP](https://github.com/mlfoundations/open_clip)
- [`facebook/dinov2-base`](https://huggingface.co/facebook/dinov2-base)
- [`microsoft/Florence-2-base`](https://huggingface.co/microsoft/Florence-2-base)
- [`microsoft/Florence-2-large`](https://huggingface.co/microsoft/Florence-2-large)
- [`MiaoshouAI/Florence-2-base-PromptGen-v2.0`](https://huggingface.co/MiaoshouAI/Florence-2-base-PromptGen-v2.0)
- [`MiaoshouAI/Florence-2-large-PromptGen-v2.0`](https://huggingface.co/MiaoshouAI/Florence-2-large-PromptGen-v2.0)
- [`HuggingFaceTB/SmolVLM-256M-Instruct`](https://huggingface.co/HuggingFaceTB/SmolVLM-256M-Instruct)
- [`HuggingFaceTB/SmolVLM2-500M-Video-Instruct`](https://huggingface.co/HuggingFaceTB/SmolVLM2-500M-Video-Instruct)
- [`vikhyatk/moondream2`](https://huggingface.co/vikhyatk/moondream2)
- [`OpenGVLab/InternVL3-1B`](https://huggingface.co/OpenGVLab/InternVL3-1B)
- [`Qwen/Qwen2.5-VL-3B-Instruct`](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct)
- [`google/paligemma2-3b-mix-224`](https://huggingface.co/google/paligemma2-3b-mix-224)
- [`fancyfeast/llama-joycaption-beta-one-hf-llava`](https://huggingface.co/fancyfeast/llama-joycaption-beta-one-hf-llava)
- [`xinyu1205/recognize-anything-plus-model`](https://huggingface.co/xinyu1205/recognize-anything-plus-model)
- [RAM++ project](https://recognize-anything.github.io/)
