# Mark Carney Tracker - [pmlog.ca](https://pmlog.ca/)
This project parses the Prime Minister's press releases from [pm.gc.ca](https://www.pm.gc.ca/en/) and transcribes and diarizes press conferences from [CPAC](https://www.cpac.ca/). All of the content is indexed with an embedding to allow for semantic search.

Through this data, journalists can follow the Prime Minister's activities in real time and trace their history of remarks on any subject. The information can be accessed, filtered, and searched using a [REST API](https://pmlog.ca/api/), [GraphQL](https://pmlog.ca/graphql) or [MCP](https://pmlog.ca/mcp).

## Tech stack
* Containerization: Docker
* Web framework: Django
* Database: Postgres
* Distributed task queue: Celery
* Broker: Redis
* Transcription model: [Whisper](https://huggingface.co/openai/whisper-small)
* Diarization model: [Speaker Verification with ECAPA-TDNN embeddings on Voxceleb](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb)
* Semantic embeddings model: [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)