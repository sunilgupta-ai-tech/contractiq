"""
Contract-aware chunking (Phase 5).

    ParsedDocument (Phase 4)
        -> structure.build_segments()   headings/numbering -> section/clause segments
        -> splitter.split_segment()     segments -> retrieval-sized pieces
        -> services/chunking_service    parent + child Chunks with metadata
        -> chunks.json                  input for embeddings (Phase 6)

See docs/chunking.md for the rules and the reasoning behind them.
"""
