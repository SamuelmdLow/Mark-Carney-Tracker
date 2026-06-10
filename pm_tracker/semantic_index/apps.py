from django.apps import AppConfig


class SemanticIndexConfig(AppConfig):
    name = "semantic_index"
    model = None

    def ready(self):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer('all-MiniLM-L6-v2')