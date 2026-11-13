# AI Usage Disclosure

## Tools used
ChatGPT (GPT-6).

# What I used them for
I used ChatGPT to interpret the Assignment A specification, propose the SQLite data model and PII-protection approach, draft the Python implementation and tests, and help document setup and design decisions.

# What I wrote or decided myself
[Describe the design choices you personally reviewed, changed, tested, and can explain. Do not claim AI-generated code as solely your own work.]

# Where the AI was wrong or unhelpful
The initial implementation plan treated the output requirements too broadly. I checked the actual assignment contract and refined the implementation around the exact five filenames, CSV headers, event-resolution order, and IST timestamp rules. Review this code and add any further examples you personally encounter.

# How I verified AI-generated code
I ran the included pytest suite. Before submitting, I will also run the supplied generator with at least one seed different from 42, ingest both drops, re-run an already ingested drop, and inspect the five report outputs. I will only submit after I can explain the code and its trade-offs in a technical discussion.
