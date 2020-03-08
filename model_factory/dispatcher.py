from sklearn import ensemble

import models

MODEL_DISPATCHER = {
    "randomforest":
    ensemble.RandomForestClassifier(n_estimators=300, verbose=2, n_jobs=-1),
    "extratrees":
    ensemble.ExtraTreesClassifier(n_estimators=300, n_jobs=-1, verbose=2),
    "resnet34":
    models.ResNet34(pretrained=True),
    "resnet50":
    models.ResNet50(pretrained=True),
    "seresnext101":
    models.SeResNext101(pretrained=True),
    'bert':
    models.BERTBaseUncased(bert_path='bert-base-uncased')
}
