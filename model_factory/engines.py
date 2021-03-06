import os
import types
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import numerapi
import numerox as nx
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import transformers
import yaml
from torch.utils.data import DataLoader

import datasets
import trainers
import utils

LOGGER = utils.get_logger(__name__)


class EngineFactory:
    @staticmethod
    def get_engine(name: str):
        if name == 'numerai':
            return NumerAIEngine
        elif name == 'bengali':
            return BengaliEngine
        elif name == 'google':
            return GoogleQAEngine
        elif name == 'imdb':
            return IMDBEngine
        else:
            return ValueError('engine name not found')


class Engine(ABC):
    """
    The Engine will combine trainers, datasets, and models
    into a single object that contains functionality to train models
    and conduct inference.

    Args:
        trainer {Trainer} - Trainer object that handles training and
        serialization.
        params {Dict} - Parameter dictionary containing engine arguments
        such as the number of epochs, paths to data, and preprocessing
        parameters
    """
    def __init__(self, trainer: trainers.BaseTrainer):
        self.trainer = trainer

    @abstractmethod
    def run_training_engine(self):
        """Wraps logic to train and evaluate"""
        raise NotImplementedError()

    @abstractmethod
    def run_inference_engine(self):
        """Wraps logic to conduct inference"""
        raise NotImplementedError()


# requires CUDA to be enabled for OSX
class BengaliEngine(Engine):
    """
    The BengaliEngine will combine trainers, datasets, and models
    into a single object that contains functionality to train models
    and conduct inference.

    Args:
        trainer {Trainer} - Trainer object that handles training and
        serialization.
        params {Dict} - Parameter dictionary containing engine arguments
        such as the number of epochs, paths to data, and preprocessing
        parameters, e.g.
            - train_path {str}: "inputs/train-folds.csv",
            - test_path {str}: "inputs",
            - pickle_path {str}: "inputs/pickled_images",
            - model_dir {str}: "trained_models",
            - train_folds {List[int]}: [0],
            - val_folds {List[int]}: [4],
            - train_batch_size {int}: 64,
            - test_batch_size {int}: 32,
            - epochs {int}: 3,
            - test_loops {int}: 5,
            - image_height {int}: 137,
            - image_width {int}: 236,
            - mean {Tuple[float]}: (0.485, 0.456, 0.406),
            - std {Tuple[float]}: (0.229, 0.239, 0.225)
    """
    def __init__(self, trainer: trainers.BaseTrainer, params: Dict):
        super().__init__(trainer)
        self.training_constructor = datasets.BengaliDataSetTrain
        self.val_constructor = datasets.BengaliDataSetTrain
        self.test_constructor = datasets.BengaliDataSetTest
        self.params = params
        self.get_available_device_ids
        self.model_name = None
        self.model_state_path = None

    @property
    def get_available_device_ids(self) -> None:
        self.device_ids = [id for id in range(torch.cuda.device_count())]
        self.available_devices = [
            device for device in self.device_ids
            if 0 <= device < torch.cuda.device_count()
        ]

    def _get_training_loader(self, folds: List[int], name: str) -> DataLoader:
        if name == "val":
            batch_size = self.params["test_batch_size"]
        else:
            batch_size = self.params["train_batch_size"]
        constructor = getattr(self, f'{name}_constructor')
        setattr(
            self, f'{name}_set',
            constructor(train_path=self.params["train_path"],
                        pickle_path=self.params["pickle_path"],
                        folds=folds,
                        image_height=self.params["image_height"],
                        image_width=self.params["image_width"],
                        mean=self.params["mean"],
                        std=self.params["std"]))
        return DataLoader(dataset=getattr(self, f'{name}_set'),
                          batch_size=batch_size,
                          shuffle=True,
                          num_workers=4)

    def _get_all_testing_loaders(self) -> List[DataLoader]:
        def _get_loader(df: pd.DataFrame) -> DataLoader:
            test_set = self.test_constructor(
                df=df,
                image_height=self.params["image_height"],
                image_width=self.params["image_width"],
                mean=self.params["mean"],
                std=self.params["std"])
            return DataLoader(dataset=test_set,
                              batch_size=self.params["test_batch_size"],
                              shuffle=False,
                              num_workers=4)

        loaders = []
        for idx in range(4):
            df = pd.read_parquet(
                f"{self.params['test_path']}/test_image_data_{idx}.parquet")
            loaders.append(_get_loader(df=df))
        return loaders

    def run_training_engine(self,
                            save_to_s3: bool = False,
                            creds: Dict = None) -> None:
        """
        Trains a ResNet34 model for the BengaliAI bengali grapheme competition.

        Args:
            save_to_s3 {bool} - save model to s3 bucket
            creds {Dict} - Dictionary containing AWS credentials. Requires
            aws_access_key_id, aws_secret_access_key, bucket. E.g.
                CREDENTIALS = {}
                CREDENTIALS['aws_access_key_id'] = os.environ.get("aws_access_key_id")
                CREDENTIALS['aws_secret_access_key'] = os.environ.get("aws_secret_access_key")
                CREDENTIALS['bucket'] = os.environ.get("bucket")
        """
        LOGGER.info(
            f'Training the model using folds: {self.params["train_folds"]}')
        LOGGER.info(
            f'Validating the model using folds {self.params["val_folds"]}')
        LOGGER.info(f'Using {len(self.device_ids)} GPUs')
        LOGGER.info(f'GPU ids: {self.device_ids}')
        if len(self.device_ids) > 1:
            LOGGER.info(f'Master Node: {self.available_devices[0]}')
            torch.cuda.set_device(self.available_devices[0])
            self.trainer.device = torch.device("cuda")
            self.trainer.model = nn.DataParallel(
                self.trainer.model, device_ids=self.available_devices)
        self.trainer.model.to(self.trainer.device)
        train = self._get_training_loader(folds=self.params["train_folds"],
                                          name='training')
        val = self._get_training_loader(folds=self.params["val_folds"],
                                        name='val')
        self.model_name = f"{self.trainer.get_model_name()}_bengali"
        model_with_val_fold = f"{self.model_name}_fold{self.params['val_folds'][0]}.pth"
        self.model_state_path = f"{self.params['model_dir']}/{model_with_val_fold}"
        best_score = -1
        for epoch in range(1, self.params["epochs"] + 1):
            LOGGER.info(f'EPOCH: {epoch}')
            train_loss, train_score = self.trainer.train(train)
            val_loss, val_score = self.trainer.evaluate(val)
            if val_score > best_score:
                best_score = val_score
                self.trainer.save_model_locally(
                    model_path=self.model_state_path)
                if save_to_s3:
                    self.trainer.save_model_to_s3(
                        filename=self.model_state_path,
                        key=model_with_val_fold,
                        creds=creds)
            LOGGER.info(
                f'Training loss: {train_loss:.3f}, Training score: {train_score:.3f}'
            )
            LOGGER.info(
                f'Validation loss: {val_loss:.3f}, Validation score: {val_score:.3f}'
            )
            self.trainer.scheduler.step(val_loss)
            self.trainer.early_stopping(val_score, self.trainer.model)
            if self.trainer.early_stopping.early_stop:
                LOGGER.info(f"Early stopping at epoch: {epoch}")
                break

    def run_inference_engine(self,
                             model_name: str,
                             model_dir: str,
                             to_csv: bool = False,
                             output_dir: str = None,
                             load_from_s3: bool = False,
                             creds: Dict = None) -> pd.DataFrame:
        """Conducts inference using the test set.

        Arguments:
            model_name {str} -- Name of the trained model.
            model_dir {str} -- Path to where the model is stored.

        Keyword Arguments:
            to_csv {bool} -- Save to csv file (default: {False})
            output_dir {str} -- Path to output directory (default: {None})
            load_from_s3 {bool} -- Load trained model from s3 bucket (default: {False})
            creds {Dict} -- Dictionary containing AWS credentials. Requires
            aws_access_key_id, aws_secret_access_key, bucket. (default: {None})
                E.g.
                CREDENTIALS = {}
                CREDENTIALS['aws_access_key_id'] = os.environ.get("aws_access_key_id")
                CREDENTIALS['aws_secret_access_key'] = os.environ.get("aws_secret_access_key")
                CREDENTIALS['bucket'] = os.environ.get("bucket")

        Returns:
            submission_df {pd.DataFrame} -- A predictions dataframe ready for submission
            to the public leaderboard.
        """
        def _conduct_inference() -> defaultdict:
            predictions = defaultdict(list)
            testing_loaders = self._get_all_testing_loaders()
            for loader in testing_loaders:
                for batch, data in enumerate(loader):
                    image = self.trainer._load_to_gpu_float(data["image"])
                    grapheme, vowel, consonant = self.trainer.model(image)
                    for idx, img_id in enumerate(data["image_id"]):
                        predictions["grapheme"].append(
                            grapheme[idx].cpu().detach().numpy())
                        predictions["vowel"].append(
                            vowel[idx].cpu().detach().numpy())
                        predictions["consonant"].append(
                            consonant[idx].cpu().detach().numpy())
                        predictions["image_id"].append(img_id)

            return predictions

        def _get_maximum_probs(preds: defaultdict) -> Dict:
            return {
                "final_grapheme":
                np.argmax(np.mean(preds["grapheme"], axis=0), axis=1),
                "final_vowel":
                np.argmax(np.mean(preds["vowel"], axis=0), axis=1),
                "final_consonant":
                np.argmax(np.mean(preds["consonant"], axis=0), axis=1),
                "image_ids":
                preds["image_id"]
            }

        def _create_submission_df(pred_dict: Dict) -> pd.DataFrame:
            predictions = []
            for idx, image_id in enumerate(pred_dict["image_ids"]):
                predictions.append((f"{image_id}_grapheme_root",
                                    pred_dict["final_grapheme"][idx]))
                predictions.append((f"{image_id}_vowel_diacritic",
                                    pred_dict["final_vowel"][idx]))
                predictions.append((f"{image_id}_consonant_diacritic",
                                    pred_dict["final_consonant"][idx]))

            return pd.DataFrame(predictions, columns=["row_id", "target"])

        final_predictions = defaultdict(list)
        for idx in range(1, self.params["test_loops"]):
            LOGGER.info(f'Conducting inference for fold {idx}')
            model_name_path = f'{model_name}_bengali_fold{idx}.pth'
            model_state_path = f'{model_dir}/{model_name_path}'
            if load_from_s3:
                self.trainer.load_model_from_s3(filename=model_state_path,
                                                key=model_name_path,
                                                creds=creds)
            self.trainer.load_model_locally(model_path=model_state_path)
            self.trainer.model.to(self.trainer.device)
            self.trainer.model.eval()
            predictions = _conduct_inference()
            final_predictions["grapheme"].append(predictions["grapheme"])
            final_predictions["vowel"].append(predictions["vowel"])
            final_predictions["consonant"].append(predictions["consonant"])
            if idx == 1:
                final_predictions["image_id"].extend(predictions["image_id"])

        pred_dictionary = _get_maximum_probs(preds=final_predictions)
        submission_df = _create_submission_df(pred_dict=pred_dictionary)
        if to_csv:
            timestamp = utils.generate_timestamp()
            output_path = f"{output_dir}/submission_{timestamp}"
            LOGGER.info(f'Saving submission dataframe to {output_path}')
            submission_df.to_csv(output_path, index=False)

        return submission_df


class GoogleQAEngine(Engine):
    def __init__(self, trainer: trainers.BaseTrainer, config_file: str):
        super().__init__(trainer)
        self.params: Dict = self.get_params(config_file)
        self.train_contructor = datasets.GoogleQADataSetTrain
        self.val_contructor = datasets.GoogleQADataSetTrain
        self.test_contructor = datasets.GoogleQADataSetTest
        self.tokenizer = transformers.BertTokenizer.from_pretrained(
            'bert-base-uncased', do_lower_case=True)

    def _get_training_loader(self, folds: List[int], name: str) -> DataLoader:
        if name == "val":
            batch_size = self.params["training_params"].get("test_batch_size")
        else:
            batch_size = self.params["training_params"].get("train_batch_size")
        constructor = getattr(self, f'{name}_constructor')
        setattr(
            self, f'{name}_set',
            constructor(
                data_folder=self.params["data_params"].get("train_path"),
                folds=folds,
                tokenizer=self.tokenzier,
                max_len=self.params["data_params"].get("max_len")))
        return DataLoader(dataset=getattr(self, f'{name}_set'),
                          batch_size=batch_size,
                          shuffle=True,
                          num_workers=4)

    def _get_testing_loader(self, folds: List[int]) -> DataLoader:
        test_set = self.test_constructor(
            data_folder=self.params["data_params"].get("test_path"),
            folds=folds,
            tokenizer=self.tokenzier,
            max_len=self.params["data_params"].get("max_len"))
        return DataLoader(dataset=test_set,
                          batch_size=self.params["test_batch_size"],
                          shuffle=False,
                          num_workers=4)

    @staticmethod
    def get_params(config_file: str) -> Dict:
        with open(config_file, 'rb') as f:
            return yaml.load(f)

    def run_training_engine(self, save_to_s3: bool = False, creds: Dict = {}):
        LOGGER.info(
            f'Training the model using folds: {self.params["training_params"].get("train_folds")}'
        )
        LOGGER.info(
            f'Validating the model using folds {self.params["training_params"].get("val_folds")[0]}'
        )
        LOGGER.info(f'Using {torch.cuda.device_count()} GPUs')
        if torch.cuda.device_count() > 1:
            self.trainer.model = nn.DataParallel(self.trainer.model)
            self.trainer.model.to(self.trainer.device)
        train = self._get_training_loader(
            folds=self.params["training_params"].get("train_folds"),
            name="train")
        val = self._get_training_loader(
            folds=self.params["training_params"].get("val_folds"), name="val")
        self.model_name = f'{self.trainer.get_model_name()}_googleqa'
        model_with_val_fold = f'{self.model_name}_fold{self.params["training_params"].get("val_folds")}.pth'
        self.model_state_path = f'{self.params["model_params"].get("model_dir")}/{model_with_val_fold}'
        best_score = -1
        for epoch in range(1,
                           self.params["training_params"].get("epochs") + 1):
            LOGGER.info(f'EPOCH: {epoch}')
            train_loss, train_score = self.trainer.train(train)
            val_loss, val_score = self.trainer.evaluate(val)
            if val_score > best_score:
                best_score = val_score
                self.trainer.save_model_locally(
                    model_path=self.model_state_path)
                if save_to_s3:
                    self.trainer.save_model_to_s3(
                        filename=self.model_state_path,
                        key=model_with_val_fold,
                        creds=creds)
            LOGGER.info(
                f'Training loss: {train_loss:.3f}, Training score: {train_score:.3f}'
            )
            LOGGER.info(
                f'Validation loss: {val_loss:.3f}, Validation score: {val_score:.3f}'
            )
            self.trainer.scheduler.step(val_loss)
            self.trainer.early_stopping(val_score, self.trainer.model)
            if self.trainer.early_stopping.early_stop:
                LOGGER.info(f'Early stopping at epoch: {epoch}')
                break

    def run_inference_engine(self):
        pass


class IMDBEngine(Engine):
    def __init__(self, trainer: trainers.BaseTrainer, config_file: str):
        super().__init__(trainer)
        self.params: Dict = self.get_params(config_file)
        self.train_contructor = datasets.IMDBDataSet
        self.val_contructor = datasets.IMDBDataSet
        self.test_contructor = datasets.IMDBDataSet
        self.tokenizer = transformers.BertTokenizer.from_pretrained(
            'bert-base-uncased', do_lower_case=True)

    def _get_training_loader(self, folds: List[int], name: str) -> DataLoader:
        if name == "val":
            batch_size = self.params["training_params"].get("test_batch_size")
        else:
            batch_size = self.params["training_params"].get("train_batch_size")
        constructor = getattr(self, f'{name}_constructor')
        setattr(
            self, f'{name}_set',
            constructor(
                data_folder=self.params["data_params"].get("train_path"),
                folds=folds,
                tokenizer=self.tokenzier,
                max_len=self.params["data_params"].get("max_len")))
        return DataLoader(dataset=getattr(self, f'{name}_set'),
                          batch_size=batch_size,
                          shuffle=True,
                          num_workers=4)

    def _get_testing_loader(self) -> DataLoader:
        setattr(
            self, 'test_set',
            self.test_constructor(
                data_folder=self.params["data_params"].get("test_path"),
                folds=self.params["training_params"].get("test_folds"),
                tokenizer=self.tokenzier,
                max_len=self.params["data_params"].get("max_len")))
        return DataLoader(dataset=getattr(self, 'test_set'),
                          batch_size=self.params["test_batch_size"],
                          shuffle=False,
                          num_workers=1)

    @staticmethod
    def get_params(config_file: str) -> Dict:
        with open(config_file, 'rb') as f:
            return yaml.load(f)

    def run_training_engine(self, save_to_s3: bool = False, creds: Dict = {}):
        LOGGER.info(
            f'Training the model using folds: {self.params["training_params"].get("train_folds")}'
        )
        LOGGER.info(
            f'Validating the model using folds {self.params["training_params"].get("val_folds")[0]}'
        )
        LOGGER.info(f'Using {torch.cuda.device_count()} GPUs')
        if torch.cuda.device_count() > 1:
            self.trainer.model = nn.DataParallel(self.trainer.model)
            self.trainer.model.to(self.trainer.device)
        train = self._get_training_loader(
            folds=self.params["training_params"].get("train_folds"),
            name="train")
        val = self._get_training_loader(
            folds=self.params["training_params"].get("val_folds"), name="val")
        self.model_name = f'{self.trainer.get_model_name()}_imdb'
        model_with_val_fold = f'{self.model_name}_fold{self.params["training_params"].get("val_folds")}.pth'
        self.model_state_path = f'{self.params["model_params"].get("model_dir")}/{model_with_val_fold}'
        best_score = -1
        for epoch in range(1,
                           self.params["training_params"].get("epochs") + 1):
            LOGGER.info(f'EPOCH: {epoch}')
            train_loss, train_score = self.trainer.train(train)
            val_loss, val_score = self.trainer.evaluate(val)
            if val_score > best_score:
                best_score = val_score
                self.trainer.save_model_locally(
                    model_path=self.model_state_path)
                if save_to_s3:
                    self.trainer.save_model_to_s3(
                        filename=self.model_state_path,
                        key=model_with_val_fold,
                        creds=creds)
            LOGGER.info(
                f'Training loss: {train_loss:.3f}, Training score: {train_score:.3f}'
            )
            LOGGER.info(
                f'Validation loss: {val_loss:.3f}, Validation score: {val_score:.3f}'
            )
            self.trainer.scheduler.step(val_loss)
            self.trainer.early_stopping(val_score, self.trainer.model)
            if self.trainer.early_stopping.early_stop:
                LOGGER.info(f'Early stopping at epoch: {epoch}')
                break

    def run_inference_engine(self):
        pass


class NumerAIEngine:
    """
    NumerAI Tournament Engine

    Arguments:
       args (types.SimpleNamespace) -- Engine arguments
        - training_config (yaml) - path to training yaml
        - competition (str) - name of competition; used to select trainer

    Methods:
        run_training_engine (self) -- train models
        run_inference_engine (self) -- conduct inference
    """
    def __init__(self,
                 training_config: str,
                 competition: str = 'numerai',
                 submit: bool = False):
        self.training_config = training_config
        self.competition = competition
        self.submit = submit
        self.tourament_names = nx.tournament_names()
        self.load_trainer_params
        self.setup_trainers
        self.setup_data

    @property
    def load_trainer_params(self) -> None:
        with open(self.training_config) as file:
            self.trainer_params = yaml.load(file)

    @property
    def setup_trainers(self) -> None:
        trainer = trainers.TrainerFactory.get_trainer(name=self.competition)
        self.trainers = [
            trainer(params=self.trainer_params, tournament=tournament)
            for tournament in self.tourament_names
        ]

    @property
    def setup_data(self):
        if self.trainer_params['get_current_data']:
            napi = numerapi.NumerAPI(verbosity="info")
            if napi.check_new_round():
                LOGGER.info('Loading current dataset from NumerAPI..')
                self.data = self.get_tournament_data()
        else:
            if os.path.isfile(self.trainer_params['local_data']):
                LOGGER.info(
                    f"Loading data locally from {self.trainer_params['local_data']}"
                )
                self.data = nx.load_zip(self.trainer_params['local_data'])
            else:
                return FileNotFoundError('local data not found')

    @staticmethod
    def get_tournament_data() -> nx.data.Data:
        try:
            data: nx.data.Data = nx.download('numerai_dataset.zip')
        except Exception as e:
            LOGGER.info(f'Failure to download numerai data with {e}')
            raise e
        return data

    def run_training_engine(self) -> None:
        for trainer in self.trainers:
            trainer.train_model(data=self.data)
            trainer.save_model_locally()
            trainer.save_to_s3()

    def run_inference_engine(self) -> Dict:
        prediction_dict = {}
        for trainer, tournament in zip(self.trainers, self.tourament_names):
            trainer.load_from_s3()
            predictions = trainer.make_predictions_and_prepare_submission(
                data=self.data, submit=self.submit)
            self.evaluate_predictions(predictions=predictions,
                                      trainer=trainer,
                                      tournament=tournament)
            prediction_dict[tournament] = predictions
        return prediction_dict

    def evaluate_predictions(self, predictions: nx.Prediction, trainer: Any,
                             tournament: str) -> None:
        """Evaluate the validation set predictions"""
        LOGGER.info(
            predictions.summaries(self.data['validation'],
                                  tournament=tournament))
        LOGGER.info(predictions[:, tournament].metric_per_era(
            data=self.data['validation'], tournament=tournament))
