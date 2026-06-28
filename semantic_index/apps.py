from django.apps import AppConfig


class SemanticIndexConfig(AppConfig):
    name = "semantic_index"
    _model = None

    def ready(self):
        import torch
        torch.set_num_threads(1)

    @property
    def model(self):
        if not self._model:            
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer('all-MiniLM-L6-v2')
        
        return self._model