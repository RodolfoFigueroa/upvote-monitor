import csv
import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from PIL import Image

from upvote_monitor.services.tagging.wd_tagger import WDTaggerResult

PIXAI_TAGGER_V0_9_ONNX_REPO_ID = "deepghs/pixai-tagger-v0.9-onnx"
PIXAI_COMPATIBLE_MODEL_REPOS = (PIXAI_TAGGER_V0_9_ONNX_REPO_ID,)
DEFAULT_MODEL_REPO_ID = PIXAI_TAGGER_V0_9_ONNX_REPO_ID
MODEL_FILENAME = "model.onnx"
TAGS_FILENAME = "selected_tags.csv"
PREPROCESS_FILENAME = "preprocess.json"
MODEL_CACHE_DIR = Path("/data/models/pixai-tagger")

GENERAL_CATEGORY = 0
CHARACTER_CATEGORY = 4


@dataclass(frozen=True)
class PixAITagLabel:
    name: str
    category: int


@dataclass(frozen=True)
class PixAIPreprocessConfig:
    size: int = 448
    mean: tuple[float, float, float] = (0.5, 0.5, 0.5)
    std: tuple[float, float, float] = (0.5, 0.5, 0.5)


class PixAITagger:
    def __init__(
        self,
        *,
        repo_id: str = DEFAULT_MODEL_REPO_ID,
        revision: str = "main",
        cache_dir: Path = MODEL_CACHE_DIR,
    ) -> None:
        self.repo_id = repo_id
        self.revision = revision
        self.model_name = repo_id
        self.model_version = revision
        self.cache_dir = cache_dir

        if repo_id not in PIXAI_COMPATIBLE_MODEL_REPOS:
            raise ValueError(
                f"Model repo is not supported by the PixAI tagger: {repo_id}"
            )

        model_path = _download_model_file(
            repo_id,
            MODEL_FILENAME,
            revision=revision,
            cache_dir=cache_dir,
        )
        tags_path = _download_model_file(
            repo_id,
            TAGS_FILENAME,
            revision=revision,
            cache_dir=cache_dir,
        )
        preprocess_path = _download_model_file(
            repo_id,
            PREPROCESS_FILENAME,
            revision=revision,
            cache_dir=cache_dir,
        )

        preprocess = _load_preprocess_config(preprocess_path)
        self._labels = _load_labels(tags_path)
        self._session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        self._input = self._session.get_inputs()[0]
        self._input_layout, self._input_size = _input_layout_and_size(
            self._input.shape,
            default_size=preprocess.size,
        )
        self._preprocess = preprocess

    def tag_image(self, path: Path) -> WDTaggerResult:
        image = _preprocess_image(
            path,
            size=self._input_size,
            layout=self._input_layout,
            mean=self._preprocess.mean,
            std=self._preprocess.std,
        )
        outputs = self._session.run(None, {self._input.name: image})
        scores = _scores_to_probabilities(
            _classification_scores(outputs, label_count=len(self._labels))
        )

        general_tags: dict[str, float] = {}
        character_tags: dict[str, float] = {}

        for label, score in zip(self._labels, scores, strict=False):
            probability = float(score)
            if label.category == CHARACTER_CATEGORY:
                character_tags[label.name] = probability
            elif label.category == GENERAL_CATEGORY:
                general_tags[label.name] = probability

        return WDTaggerResult(
            ratings={},
            general_tags=general_tags,
            character_tags=character_tags,
        )


@lru_cache(maxsize=2)
def get_pixai_tagger(
    repo_id: str = DEFAULT_MODEL_REPO_ID,
    revision: str = "main",
) -> PixAITagger:
    return PixAITagger(repo_id=repo_id, revision=revision)


def _download_model_file(
    repo_id: str,
    filename: str,
    *,
    revision: str,
    cache_dir: Path,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        revision=revision,
        cache_dir=str(cache_dir),
    )
    return Path(path)


def _load_labels(path: Path) -> list[PixAITagLabel]:
    with open(path, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        labels: list[PixAITagLabel] = []
        for row in reader:
            name = str(row["name"]).strip()
            category = int(row["category"])
            labels.append(PixAITagLabel(name=name, category=category))
        return labels


def _load_preprocess_config(path: Path) -> PixAIPreprocessConfig:
    with open(path, encoding="utf-8") as file:
        raw = json.load(file)

    size = 448
    mean = (0.5, 0.5, 0.5)
    std = (0.5, 0.5, 0.5)

    for stage in _preprocess_stages(raw):
        stage_type = stage.get("type")
        if stage_type == "resize":
            size = _preprocess_size(stage.get("size")) or size
        elif stage_type == "normalize":
            mean = _float_triplet(stage.get("mean")) or mean
            std = _float_triplet(stage.get("std")) or std

    return PixAIPreprocessConfig(size=size, mean=mean, std=std)


def _preprocess_stages(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    stages = raw.get("stages")
    if not isinstance(stages, list):
        return []
    return [stage for stage in stages if isinstance(stage, dict)]


def _preprocess_size(value: Any) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if (
        isinstance(value, list)
        and len(value) >= 1
        and isinstance(value[0], int)
        and value[0] > 0
    ):
        return value[0]
    return None


def _float_triplet(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, list) or len(value) != 3:
        return None
    result: list[float] = []
    for item in value:
        if not isinstance(item, int | float):
            return None
        result.append(float(item))
    return (result[0], result[1], result[2])


def _input_layout_and_size(
    shape: list[int | str | None],
    *,
    default_size: int,
) -> tuple[str, int]:
    if len(shape) != 4:
        return "NCHW", default_size

    channel_first = _shape_int(shape[1]) in (1, 3)
    if channel_first:
        height = _shape_int(shape[2]) or default_size
        return "NCHW", height

    height = _shape_int(shape[1]) or default_size
    return "NHWC", height


def _shape_int(value: int | str | None) -> int | None:
    return value if isinstance(value, int) and value > 0 else None


def _preprocess_image(
    path: Path,
    *,
    size: int,
    layout: str,
    mean: tuple[float, float, float],
    std: tuple[float, float, float],
) -> np.ndarray:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        rgb = background.convert("RGB")
        resized = rgb.resize((size, size), Image.Resampling.BILINEAR)

    array = np.asarray(resized, dtype=np.float32) / 255.0
    mean_array = np.asarray(mean, dtype=np.float32)
    std_array = np.asarray(std, dtype=np.float32)
    array = (array - mean_array) / std_array
    if layout == "NCHW":
        array = np.transpose(array, (2, 0, 1))
    return np.expand_dims(array, axis=0)


def _classification_scores(outputs: Sequence[Any], *, label_count: int) -> np.ndarray:
    flattened_outputs = [np.asarray(output).reshape(-1) for output in outputs]
    for output in flattened_outputs:
        if output.size == label_count:
            return output
    if len(flattened_outputs) == 1:
        return flattened_outputs[0]

    sizes = ", ".join(str(output.size) for output in flattened_outputs)
    raise ValueError(
        "PixAI ONNX outputs did not include classification scores "
        f"for {label_count} labels; output sizes were: {sizes}"
    )


def _scores_to_probabilities(scores: np.ndarray) -> np.ndarray:
    probabilities = np.asarray(scores, dtype=np.float32)
    if np.any((probabilities < 0.0) | (probabilities > 1.0)):
        probabilities = 1.0 / (1.0 + np.exp(-np.clip(probabilities, -60.0, 60.0)))
    return probabilities
