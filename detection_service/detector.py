import io
import logging
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

import numpy as np
from PIL import Image

from common.config import settings

logger = logging.getLogger(__name__)


class AnimalDetector:
    def __init__(self):
        self.model = None
        self.animal_classes = set(settings.animal_class_list)
        self.confidence_threshold = settings.CONFIDENCE_THRESHOLD
        self.model_path = settings.YOLO_MODEL_PATH
        self._model_loaded = False
        self._all_class_names = {}

    def _load_model(self):
        if self._model_loaded:
            return
        try:
            from ultralytics import YOLO
            logger.info(f"Loading YOLO model from {self.model_path}...")

            model_file = Path(self.model_path)
            if not model_file.exists():
                logger.info(f"Model file not found, will download: {self.model_path}")

            self.model = YOLO(self.model_path)
            self._all_class_names = self.model.names if hasattr(self.model, "names") else {}
            self._model_loaded = True
            logger.info(
                f"YOLO model loaded successfully. Classes: {len(self._all_class_names)}, "
                f"Target animal classes: {self.animal_classes}"
            )
        except ImportError:
            logger.error("ultralytics not installed. Install with: pip install ultralytics")
            raise
        except Exception as e:
            logger.exception(f"Failed to load YOLO model: {e}")
            raise

    def _ensure_loaded(self):
        if not self._model_loaded:
            self._load_model()

    def _is_animal_class(self, class_name: str) -> bool:
        name_lower = class_name.lower()
        if name_lower in self.animal_classes:
            return True
        for animal in self.animal_classes:
            if animal in name_lower or name_lower in animal:
                return True
        return False

    def detect(
        self,
        image_bytes: bytes,
        conf_threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        self._ensure_loaded()

        threshold = conf_threshold if conf_threshold is not None else self.confidence_threshold

        try:
            image = Image.open(io.BytesIO(image_bytes))
            if image.mode != "RGB":
                image = image.convert("RGB")

            results = self.model.predict(
                source=np.array(image),
                conf=threshold,
                verbose=False,
            )

            detections: List[Dict[str, Any]] = []
            animal_detections: List[Dict[str, Any]] = []
            max_confidence = 0.0
            has_animal = False
            detected_class_names = set()

            if results and len(results) > 0:
                result = results[0]

                if result.boxes is not None and len(result.boxes) > 0:
                    boxes = result.boxes
                    for i in range(len(boxes)):
                        cls_id = int(boxes.cls[i].item()) if hasattr(boxes.cls[i], "item") else int(boxes.cls[i])
                        conf = float(boxes.conf[i].item()) if hasattr(boxes.conf[i], "item") else float(boxes.conf[i])
                        xyxy = boxes.xyxy[i].tolist() if hasattr(boxes.xyxy[i], "tolist") else list(boxes.xyxy[i])

                        class_name = self._all_class_names.get(cls_id, f"class_{cls_id}")
                        is_animal = self._is_animal_class(class_name)

                        detection = {
                            "class_name": class_name,
                            "confidence": conf,
                            "bbox_x1": float(xyxy[0]),
                            "bbox_y1": float(xyxy[1]),
                            "bbox_x2": float(xyxy[2]),
                            "bbox_y2": float(xyxy[3]),
                            "is_animal": is_animal,
                        }
                        detections.append(detection)
                        detected_class_names.add(class_name)

                        if is_animal:
                            animal_detections.append(detection)
                            has_animal = True
                            if conf > max_confidence:
                                max_confidence = conf

            if not has_animal:
                max_confidence = 0.0
                for d in detections:
                    if d["confidence"] > max_confidence:
                        max_confidence = d["confidence"]

            return {
                "has_animal": has_animal,
                "max_confidence": max_confidence,
                "total_detections": len(detections),
                "animal_detection_count": len(animal_detections),
                "detections": detections,
                "animal_detections": animal_detections,
                "detected_classes": sorted(list(detected_class_names)),
            }

        except Exception as e:
            logger.exception(f"Detection failed: {e}")
            raise


_detector_instance: Optional[AnimalDetector] = None


def get_detector() -> AnimalDetector:
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = AnimalDetector()
    return _detector_instance
