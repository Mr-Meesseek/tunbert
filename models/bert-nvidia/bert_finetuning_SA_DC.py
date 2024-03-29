# Copyright (c) 2020, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# Example SA:
# python models/bert-nvidia/bert_finetuning_SA_DC.py --config-name "sentiment_analysis_config"
# Example DC:
# python models/bert-nvidia/bert_finetuning_SA_DC.py --config-name "dialect_classification_config"


"""
This script trains, evaluates and perform inference with the TextClassificationModel.
TextClassificationModel in NeMo supports text classification problems such as sentiment analysis(SA)
and dialect classification(DC), as long as the data follows the format specified below.
***Data format***
TextClassificationModel requires the data to be stored in TAB separated files (.tsv) with two columns of sentence and
label. Each line of the data file contains text sequences, where words are separated with spaces and label separated
with [TAB], i.e.:
[WORD][SPACE][WORD][SPACE][WORD][TAB][LABEL]
"""
import os

import pytorch_lightning as pl
import torch
from nemo.collections.nlp.models.text_classification import TextClassificationModel
from nemo.core.config import hydra_runner
from nemo.utils import logging
from nemo.utils.exp_manager import exp_manager
from omegaconf import DictConfig, OmegaConf


@hydra_runner(
    config_path="configs", config_name="sentiment_analysis_config"
)  # config_name="dialect_classification_config" for DC task
def main(cfg: DictConfig) -> None:
    logging.info(f"\nConfig Params:\n{cfg.pretty()}")
    trainer = pl.Trainer(**cfg.trainer)
    exp_manager(trainer, cfg.get("exp_manager", None))

    if not cfg.model.train_ds.file_path:
        raise ValueError("'train_ds.file_path' need to be set for the training!")

    model = TextClassificationModel(cfg.model, trainer=trainer)
    logging.info(
        "==========================================================================================="
    )
    logging.info("Starting training...")
    trainer.fit(model)
    logging.info("Training finished!")
    logging.info(
        "==========================================================================================="
    )

    if cfg.model.nemo_path:
        model.save_to(cfg.model.nemo_path)
        logging.info(f"Model is saved into `.nemo` file: {cfg.model.nemo_path}")

    # We evaluate the trained model on the test set if test_ds is set in the config file
    if cfg.model.test_ds.file_path:
        logging.info(
            "==========================================================================================="
        )
        logging.info("Starting the testing of the trained model on test set...")
        # The latest checkpoint would be used, set ckpt_path to 'best' to use the best one
        trainer.test(model=model, ckpt_path=None, verbose=False)
        logging.info("Testing finished!")
        logging.info(
            "==========================================================================================="
        )

    # retrieve the path to the last checkpoint of the training
    if trainer.checkpoint_callback is not None:
        checkpoint_path = os.path.join(
            trainer.checkpoint_callback.dirpath,
            trainer.checkpoint_callback.prefix + "end.ckpt",
        )
    else:
        checkpoint_path = None
    """
    After model training is done, if you have saved the checkpoints, you can create the model from
    the checkpoint again and evaluate it on a data file.
    You need to set or pass the test dataloader, and also create a trainer for this.
    """
    if (
        checkpoint_path
        and os.path.exists(checkpoint_path)
        and cfg.model.validation_ds.file_path
    ):
        logging.info(
            "==========================================================================================="
        )
        logging.info(
            "Starting the evaluating the the last checkpoint on a data file (validation set by default)..."
        )
        # we use the the path of the checkpoint from last epoch from the training, you may update it to any checkpoint
        # Create an evaluation model and load the checkpoint
        eval_model = TextClassificationModel.load_from_checkpoint(
            checkpoint_path=checkpoint_path
        )

        # create a dataloader config for evaluation, the same data file provided in validation_ds is used here
        # file_path can get updated with any file
        eval_config = OmegaConf.create(
            {
                "file_path": cfg.model.validation_ds.file_path,
                "batch_size": 64,
                "shuffle": False,
            }
        )
        eval_model.setup_test_data(test_data_config=eval_config)

        # a new trainer is created to show how to evaluate a checkpoint from an already trained model
        # create a copy of the trainer config and update it to be used for final evaluation
        eval_trainer_cfg = cfg.trainer.copy()

        # it is safer to perform evaluation on single GPU without ddp as we are creating second trainer in
        # the same script, and it can be a problem with multi-GPU training.
        # We also need to reset the environment variable PL_TRAINER_GPUS to prevent PT from initializing ddp.
        # When evaluation and training scripts are in separate files, no need for this resetting.
        eval_trainer_cfg.gpus = 1 if torch.cuda.is_available() else 0
        eval_trainer_cfg.distributed_backend = None
        eval_trainer = pl.Trainer(**eval_trainer_cfg)

        eval_trainer.test(
            model=eval_model, verbose=False
        )  # test_dataloaders=eval_dataloader,

        logging.info("Evaluation the last checkpoint finished!")
        logging.info(
            "==========================================================================================="
        )
    else:
        logging.info(
            "No file_path was set for validation_ds or no checkpoint was found, so final evaluation is skipped!"
        )

    if checkpoint_path and os.path.exists(checkpoint_path):
        # You may create a model from a saved chechpoint and use the model.infer() method to
        # perform inference on a list of queries. There is no need of any trainer for inference.
        logging.info(
            "==========================================================================================="
        )
        logging.info("Starting the inference on some sample queries...")
        queries = [
            "استفدت برشا نعشق فيديوهاتك و نحب نعرف وقتاه تعلمت هذ الكل",
            "بصراحة أحسن حاجة كيف رجعتو كريم القنات نورت بيك ربي يوفقك يا خويا كريم يا باهي",
            "المسلسل هاذا رغم سقاطتو و رغم كلشي فيه اما فيه برشا حاجات مش خايبين",
            "الله اعز مسلسل تونسي",
            " رجعتوا لفساد بطولة و لخماج قفازة  حسبنا الله ونعم الوكيل",
            "والله لا تحشم.. عيب عليك.. تحب تفدلك على ربي!!!!!! يعني لا دين، لا ملة",
        ]

        # use the path of the last checkpoint from the training, you may update it to any other checkpoints
        infer_model = TextClassificationModel.load_from_checkpoint(
            checkpoint_path=checkpoint_path
        )

        # move the model to the desired device for inference
        # we move the model to "cuda" if available otherwise "cpu" would be used
        if torch.cuda.is_available():
            infer_model.to("cuda")
        else:
            infer_model.to("cpu")

        # max_seq_length=512 is the maximum length BERT supports.
        results = infer_model.classifytext(queries=queries, batch_size=16)

        logging.info(
            "The prediction results of some sample queries with the trained model:"
        )
        for query, result in zip(queries, results):
            logging.info(f"Query : {query}")
            logging.info(f"Predicted label: {result}")

        logging.info("Inference finished!")
        logging.info(
            "==========================================================================================="
        )
    else:
        logging.info(
            "Inference is skipped as no checkpoint was found from the training!"
        )


if __name__ == "__main__":
    main()
