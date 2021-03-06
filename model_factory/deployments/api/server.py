from concurrent.futures import ThreadPoolExecutor

import grpc

import numerai_pb2
import numerai_pb2_grpc
import utils
from engines import NumerAIEngine

LOGGER = utils.get_logger(__name__)


class NumerAIEngineAPI(numerai_pb2_grpc.NumerAIEngineAPIServicer):
    def Train(self, request, context):
        engine = NumerAIEngine(training_config=request.config,
                               competition=request.competition)
        engine.run_training_engine()

    def Predict(self, request, context):
        engine = NumerAIEngine(training_config=request.config,
                               competition=request.competition,
                               submit=request.submit)
        predictions = engine.run_inference_engine()
        for tournament, prediction in predictions.items():
            LOGGER.info(prediction.df.head())


def serve():
    LOGGER.info("Starting server..")
    server = grpc.server(ThreadPoolExecutor(max_workers=10))
    numerai_pb2_grpc.add_NumerAIEngineAPIServicer_to_server(
        NumerAIEngineAPI(), server)
    server.add_insecure_port('[::]:50052')
    server.start()
    LOGGER.info("Server started")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
