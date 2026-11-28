"""Plan queries, recall candidates, rank evidence and execute model rerankers.

orchestrator.run_retrieval assembles the ordered stages; this package marker
does not load query backends, model providers or graph execution.
"""
