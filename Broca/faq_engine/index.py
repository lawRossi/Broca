from elasticsearch import Elasticsearch
from semantic_matching.index import AnnoyIndex
from semantic_matching.wrapper import EncoderWrapper


class ESIndex:
    def __init__(self, es, es_index):
        self. es = es
        self.es_index = es_index

    @classmethod
    def from_config(cls, config):
        es = Elasticsearch(config.get("hosts"), http_auth=config.get("http_auth"))
        return cls(es, config["index"])

    def build_index(self, documents):
        self._check_index()
        for document in documents:
            self.es.index(self.es_index, document, id=document["id"])

    def add_documents(self, documents):
        for document in documents:
            self.es.index(self.es_index, document, id=document["id"])

    def _check_index(self):
        es = self.es
        if not es.indices.exists(self.es_index):
            es.indices.create(self.es_index)
            es.indices.close(self.es_index)
            setting = {
                "index.analysis.analyzer.default.type": "ik_max_word",
                "index.analysis.search_analyzer.default.type": "ik_samrt"
            }
            es.indices.put_settings(setting, index=self.es_index)
            es.indices.open(self.es_index)

    def get_documents_by_ids(self, document_ids):
        result = self.es.mget({"ids": document_ids}, index=self.es_index)
        documents = [doc["_source"] for doc in result["docs"]]
        return documents


class VectorIndex:
    def __init__(self, index):
        self.index = index
    
    @classmethod
    def from_config(cls, config):
        encoder_model = config["encoder_model"]
        encoder = EncoderWrapper(encoder_model, device=config["device"])
        index = AnnoyIndex(encoder, config["index_dir"])
        index.load_index()
        return cls(index)
    
    def retrieve(self, query, topk):
        return self.index.retrieve(query, topk, include_similarity=True)


if __name__ == "__main__":
    from elasticsearch import Elasticsearch

    es = Elasticsearch(["81.68.99.110"], http_auth=('elastic', 'xiaoxi2203'))
    index = ESIndex(es, "questions")
    index.build_index([{"id": "123", "question": "你叫什么名字？"}, {"id": "124", "question": "你来自哪里？"}])
    print(index.get_documents_by_ids(["123", "124"]))
