# MODEL-PIPELINES

This is my personal repository to build pipelines that preprocess data, train models, make inference, and are able to be productionized using AWS or GCP. I set up it so that it can work with different ML API's such as scikit-learn, pytorch, xgboost, etc. and multiple types of datasets.

It's a WIP so I'll be regularly changing things to reduce complexity, deal with bugs, and allow the package to generalize to more types of ML problems. My end goal is for this package to be starter code for others to use and integrate into their own projects. Happy modeling!

Using inspiration from https://github.com/bgweber and https://github.com/abhishekkrthakur.

# Setup

1. Create a virtual environment using conda, virtualenv, virtualenvwrapper, etc. then pip install the requirements. For example:
```
cd model_factory
conda create -n model_pipelines python=3.6
conda activate model_pipelines
conda install pytorch torchvision -c pytorch -y
pip install -r requirements.txt
```

2. Download a dataset and store it in `inputs` for example:`
    - `mkdir inputs` && `cd inputs`
    - `mkdir quora_question_pairs` && `cd quora_question_pairs`
    - `kaggle competitions download -c quora-question-pairs`

3. Train a model and set MODEL_PATH - e.g. `export MODEL_PATH=trained_models/<model-name>`:

    - `mkdir trained_models`

4. Set up connections to AWS or GCP. This step is a little more involved so checkout the documentation:

    - AWS: https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-configure.html#cli-quick-configuration
    - GCP: https://cloud.google.com/sdk/gcloud/reference/auth/login

# Training Models

This API is still a WIP so it will probably change.

1. Setup your CrossValidator object and create training and validation folds.

2. Setup your DataSet object by pointing to your dataset - e.g. inputs/<data-folder> - and decide on what fold you want you use.

3. Setup your Model by wrapping an sklearn, xgboost, pytorch, or keras model into a Model object that we will use inside of a Trainer.

3. Trainers group training and inference functionality to abstract away a lot of detail and get you going. They have the ability to load/save trained models to/from s3 buckets (GCP coming soon). More functionality will be added to simplify things.

4. Create your Engine object and instantiate your model, pass it into your trainer, and pass the trainer to your Engine object. The Engine handles training using the `engine.run_training_engine()` method and inference using `engine.run_inference_engine()`. Look at the docstrings to see the required arguments.

5. Optional: setup a credentials dictionary containing your AWS login information. Doing this will allow you to save and load models from and to an s3 bucket.

# Webapps

### Deploy web application locally

1. `cd deployments/webapp`

2. `sh bash_scripts/run-app.sh`


# Pipelines

Im working on integrating Airflow into the package so that pipelines can be orchestrated and deployed on a kubernetes cluster. More coming soon!


### Run example pipeline

1. `cd deployments/pipelines/example_pipeline`

2. Setup pipeline-creds.json containing all of your GCP credentials info.

3. Setup environmental variables:
    - `export PROJECT_ID=<project-id>`
    - `export IMAGE_NAME=<image-name>`
    - `export CREDS=<path-to-creds-file>`

4. Run the setup scripts:
    - `sh set-up-creds.sh && sh push-to-gcr.io`
