"""Ask a question of your datasets; the answer cites the records it used.

    python examples/ask_with_citations.py "Which lamps cost under 20 EUR?" [dataset_id]
"""

import sys

from scrawl import Scrawl

question = sys.argv[1]
dataset_id = sys.argv[2] if len(sys.argv) > 2 else None
with Scrawl() as client:
    result = client.ask(question, dataset_id=dataset_id)          # uses your default AI profile
    print(result.answer)
    for citation in result.citations:
        print(f"  [{citation.tag}] {citation.title} {citation.url} (document {citation.document_id})")
    if not result.answerable:
        print("(the datasets do not answer this)", file=sys.stderr)
