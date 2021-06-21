from elasticsearch import Elasticsearch
import json
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
            answer = {"content": document["answer"], "join_field": {"name": "answer"}}
            res = self.es.index(self.es_index, answer)
            answer_id = res["_id"]
            for q in document["questions"]:
                question = {"content": q, "join_field": {"name": "question", "parent": answer_id}}
                self.es.index(self.es_index, question, routing=answer_id)

    def build_index_from_file(self, document_file):
        print("start building es index")
        with open(document_file, encoding="utf-8") as fi:
            documents = []
            for line in fi:
                documents.append(json.loads(line))
            self.build_index(documents)

    def add_documents(self, documents):
        for document in documents:
            self.es.index(self.es_index, document, id=document["id"])

    def _check_index(self):
        es = self.es
        if es.indices.exists(self.es_index):
            es.indices.delete(self.es_index)
        es.indices.create(self.es_index)
        es.indices.close(self.es_index)
        setting = {
            "index.analysis.analyzer.default.type": "ik_max_word",
            "index.analysis.search_analyzer.default.type": "ik_samrt"
        }
        es.indices.put_settings(setting, index=self.es_index)
        mappings = {
            "properties": {
                "text": {"type": "text"},
                "join_field": { 
                    "type": "join",
                    "relations": {
                        "answer": "question" 
                    }
                }
            }
        }
        es.indices.put_mapping(mappings, index=self.es_index)
        es.indices.open(self.es_index)

    def get_documents_by_ids(self, document_ids):
        result = self.es.mget({"ids": document_ids}, index=self.es_index)
        documents = [doc["_source"] for doc in result["docs"]]
        return documents

    def get_answer_by_question_ids(self, question_ids):
        query = {
            "query": {
                "has_child": { 
                    "type": "question",
                    "query" : {
                        "terms": {
                            "_id": question_ids
                        }
                    }
                }
            }
        }
        # query = {"query": {"match_all": {}}}
        res = self.es.search(body=query, index=self.es_index)
        ids = set()
        answers = []
        for hit in res["hits"]["hits"]:
            if hit["_id"] not in ids:
                answer = hit["_source"]
                answer["id"] = hit["_id"]
                answers.append(hit["_source"])
                ids.add(hit["_id"])
        return answers

    def get_all_questions(self):
        res = self.es.search(index=self.es_index, body={"query": {"match_all": {}}}, scroll='10m', size=1000)
        questions = []
        for hit in res["hits"]["hits"]:
            if hit["_source"]["join_field"]["name"] == "question":
                question = {"id": hit["_id"], "index_text": hit["_source"]["content"]}
                questions.append(question)
        scroll_id = res['_scroll_id']
        total = res['hits']['total']["value"]
        for _ in range(total//1000+1):
            res = self.es.scroll(scroll_id=scroll_id, scroll="2m")
            for hit in res["hits"]["hits"]:
                if hit["_source"]["join_field"]["name"] == "question":
                    question = {"id": hit["_id"], "index_text": hit["content"]}
                    questions.append(question)
        return questions


class VectorIndex:
    def __init__(self, index):
        self.index = index
    
    @classmethod
    def from_config(cls, config):
        encoder_model = config["encoder_model"]
        encoder = EncoderWrapper(encoder_model, device=config["device"])
        index = AnnoyIndex(encoder, config["index_dir"])
        return cls(index)

    def load_index(self):
        self.index.load_index()

    def retrieve(self, query, topk):
        return self.index.retrieve(query, topk, include_similarity=True)

    def build_index(self, es_index):
        questions = es_index.get_all_questions()
        print(f"building index with {len(questions)} questions")
        self.index.build_index(questions)


if __name__ == "__main__":
    from elasticsearch import Elasticsearch

    es = Elasticsearch(["81.68.99.110"], http_auth=('elastic', 'xiaoxi2203'))
    index = ESIndex(es, "questions")
    # index.build_index_from_file("tests/data/questions.json")
    # print(index.get_documents_by_ids(["123", "124", "111"]))
    # print(index.get_answer_by_question_ids(["123", "124"]))
    print(index.get_all_questions())
