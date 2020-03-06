import glob
import os
from typing import Any, Dict, List, Tuple

import albumentations
import joblib
import numpy as np
import pandas as pd
import torch
import torchvision
from PIL import Image
from sklearn import model_selection
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm

import utils

LOGGER = utils.get_logger(__name__)


class BengaliDataSetTrain(Dataset):
    """
    Dataset for training/validation.

    Args:
        train_path {str} - path to train-folds.csv
        pickle_path {str} - path to pickled images
        folds {List[int]} - key for dataset fold
        image_height {int} - height of images
        image_width {int} - width of images
        mean {Tuple[float]} - mean for image augmentation
        std {Tuple[float]} - variance for image augmentation
    """
    def __init__(self,
                 train_path: str,
                 pickle_path: str = None,
                 folds: List[int] = [0],
                 image_height: int = None,
                 image_width: int = None,
                 mean: Tuple[float] = None,
                 std: Tuple[float] = None):
        self.train_path = train_path
        self.folds = folds
        self.image_height = image_height
        self.image_width = image_width
        self.mean = mean
        self.std = std
        self.pickle_path = pickle_path
        self._create_attributes()
        self._create_augmentations()

    def _create_attributes(self) -> None:
        def _load_df() -> pd.DataFrame:
            df = pd.read_csv(self.train_path)
            df = df.drop('grapheme', axis=1)
            return df.loc[df.kfold.isin(self.folds)].reset_index(drop=True)

        df = _load_df()
        self.image_ids = df.image_id.values
        self.grapheme_root = df.grapheme_root.values
        self.vowel_diacritic = df.vowel_diacritic.values
        self.consonant_diacritic = df.consonant_diacritic.values

    def _create_augmentations(self) -> None:
        if len(self.folds) > 1:
            self.aug = albumentations.Compose([
                albumentations.Resize(self.image_height,
                                      self.image_width,
                                      always_apply=True),
                albumentations.Normalize(self.mean,
                                         self.std,
                                         always_apply=True)
            ])
        else:
            self.aug = albumentations.Compose([
                albumentations.Resize(self.image_height,
                                      self.image_width,
                                      always_apply=True),
                albumentations.ShiftScaleRotate(shift_limit=0.0625,
                                                scale_limit=0.1,
                                                rotate_limit=5,
                                                p=0.9),
                albumentations.Normalize(self.mean,
                                         self.std,
                                         always_apply=True)
            ])

    def __len__(self):
        return len(self.image_ids)

    def __getitem__(self, item: int) -> Dict:
        def _prepare_image() -> Image:
            image = joblib.load(f"{self.pickle_path}/{self.image_ids[item]}.p")
            image = image.reshape(self.image_height,
                                  self.image_width).astype(float)
            return Image.fromarray(image).convert("RGB")

        def _augment_image(image) -> np.array:
            image = self.aug(image=np.array(image))["image"]
            return np.transpose(image, (2, 0, 1)).astype(np.float32)

        def _return_image_dict(image) -> Dict:
            return {
                "image":
                torch.tensor(image, dtype=torch.float),
                "grapheme_root":
                torch.tensor(self.grapheme_root[item], dtype=torch.long),
                "vowel_diacritic":
                torch.tensor(self.vowel_diacritic[item], dtype=torch.long),
                "consonant_diacritic":
                torch.tensor(self.consonant_diacritic[item], dtype=torch.long),
            }

        image = _prepare_image()
        image = _augment_image(image=image)
        return _return_image_dict(image=image)


class BengaliDataSetTest(Dataset):
    """
    Dataset for inference.

    Args:
        df {pd.DataFrame} - parquet dataframe with test images
        image_height {int} - height of images
        image_width {int} - width of images
        mean {Tuple[float]} - mean for image augmentation
        std {Tuple[float]} - variance for image augmentation
    """
    def __init__(self,
                 df: pd.DataFrame,
                 image_height: int = None,
                 image_width: int = None,
                 mean: float = None,
                 std: float = None):
        self.df = df
        self.image_height = image_height
        self.image_width = image_width
        self.mean = mean
        self.std = std
        self._create_attributes()
        self._create_augmentations()

    def _create_attributes(self) -> None:
        self.image_ids = self.df.image_id.values
        self.image_arr = self.df.iloc[:, 1:].values

    def _create_augmentations(self) -> None:
        self.aug = albumentations.Compose([
            albumentations.Resize(self.image_height,
                                  self.image_width,
                                  always_apply=True),
            albumentations.Normalize(self.mean, self.std, always_apply=True)
        ])

    def __len__(self):
        return len(self.image_ids)

    def __getitem__(self, item: int) -> Dict:
        def _prepare_image() -> Image:
            image = self.image_arr[item, :]
            image = image.reshape(self.image_height,
                                  self.image_width).astype(float)
            return Image.fromarray(image).convert("RGB")

        def _augment_image(image) -> np.array:
            image = self.aug(image=np.array(image))["image"]
            return np.transpose(image, (2, 0, 1)).astype(np.float32)

        def _get_image_id() -> int:
            return self.image_id[item]

        def _return_image_dict(image, image_id) -> Dict:
            return {
                "image": torch.tensor(image, dtype=torch.float),
                "image_id": image_id
            }

        image = _prepare_image()
        augmented_image = _augment_image(image=image)
        image_id = _get_image_id()
        return _return_image_dict(image=augmented_image, image_id=image_id)