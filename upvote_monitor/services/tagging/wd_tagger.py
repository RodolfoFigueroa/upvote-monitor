import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from PIL import Image

DEFAULT_MODEL_REPO_ID = "SmilingWolf/wd-v1-4-vit-tagger-v2"
MODEL_FILENAME = "model.onnx"
TAGS_FILENAME = "selected_tags.csv"
MODEL_CACHE_DIR = Path("/data/models/wd-tagger")

RATING_CATEGORY = 9
GENERAL_CATEGORY = 0
CHARACTER_CATEGORY = 4


@dataclass(frozen=True)
class TagLabel:
    name: str
    category: int


@dataclass(frozen=True)
class WDTaggerResult:
    ratings: dict[str, float]
    general_tags: dict[str, float]
    character_tags: dict[str, float]


class WDTagger:
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

        self._labels = _load_labels(tags_path)
        self._session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        self._input = self._session.get_inputs()[0]
        self._input_layout, self._input_size = _input_layout_and_size(self._input.shape)

    def tag_image(self, path: Path) -> WDTaggerResult:
        image = _preprocess_image(
            path,
            size=self._input_size,
            layout=self._input_layout,
        )
        outputs = self._session.run(None, {self._input.name: image})
        scores = np.asarray(outputs[0]).reshape(-1)

        ratings: dict[str, float] = {}
        general_tags: dict[str, float] = {}
        character_tags: dict[str, float] = {}

        for label, score in zip(self._labels, scores, strict=False):
            probability = float(score)
            if label.category == RATING_CATEGORY:
                ratings[label.name] = probability
            elif label.category == CHARACTER_CATEGORY:
                character_tags[label.name] = probability
            elif label.category == GENERAL_CATEGORY:
                general_tags[label.name] = probability

        return WDTaggerResult(
            ratings=ratings,
            general_tags=general_tags,
            character_tags=character_tags,
        )


@lru_cache(maxsize=2)
def get_wd_tagger(
    repo_id: str = DEFAULT_MODEL_REPO_ID,
    revision: str = "main",
) -> WDTagger:
    return WDTagger(repo_id=repo_id, revision=revision)


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


def _load_labels(path: Path) -> list[TagLabel]:
    with open(path, newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        labels: list[TagLabel] = []
        for row in reader:
            name = str(row["name"]).strip()
            category = int(row["category"])
            labels.append(TagLabel(name=name, category=category))
        return labels


def _input_layout_and_size(shape: list[int | str | None]) -> tuple[str, int]:
    if len(shape) != 4:
        return "NHWC", 448

    channel_first = _shape_int(shape[1]) in (1, 3)
    if channel_first:
        height = _shape_int(shape[2]) or 448
        return "NCHW", height

    height = _shape_int(shape[1]) or 448
    return "NHWC", height


def _shape_int(value: int | str | None) -> int | None:
    return value if isinstance(value, int) and value > 0 else None


def _preprocess_image(path: Path, *, size: int, layout: str) -> np.ndarray:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        rgb = _square_pad(background.convert("RGB"))
        resized = rgb.resize((size, size), Image.Resampling.LANCZOS)

    array = np.asarray(resized, dtype=np.float32)
    array = array[:, :, ::-1]
    if layout == "NCHW":
        array = np.transpose(array, (2, 0, 1))
    return np.expand_dims(array, axis=0)


def _square_pad(image: Image.Image) -> Image.Image:
    width, height = image.size
    side = max(width, height)
    if width == height:
        return image

    result = Image.new("RGB", (side, side), (255, 255, 255))
    result.paste(image, ((side - width) // 2, (side - height) // 2))
    return result
