from __future__ import annotations

from houbridge.search.dense import DenseIndexSchema
from houbridge.search.lexical import LexicalIndexSchema


SOURCE_EMBEDDING_TABLE = "history_source_embeddings"
DENSE_NAMESPACE = "history-source"
LEXICAL_NAMESPACE = "history-action"
DENSE_SCHEMA = DenseIndexSchema(
    profile_table="history_vector_profiles",
    vector_table_prefix="history_vec",
)
LEXICAL_SCHEMA = LexicalIndexSchema(
    entry_table="history_lexical_entries",
    fts_table="history_lexical_fts",
)
