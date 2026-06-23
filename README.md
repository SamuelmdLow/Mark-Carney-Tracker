# Mark Carney Tracker
The purpose of this project is to make the activities and statements of the Prime Minister easier to follow and search.

## What it does
The project parses the Prime Minister's media advisory pages and saves their information in its database. Videos from cpac.ca which are deemed relevant to a schedule item are transcribed and also saved in the database. Everything is then indexed with an embedding to allow for semantic search.

The information can be accessed, filtered, and searched using a REST api or with GraphQL.

## Tech stack
The database is Postgres and Django is the web framework. Celery is used for background tasks with Redis responsible for task queues. Whisper is used for transcription and all-MiniLM-L6-v2 is the embedding model used for semantic search.