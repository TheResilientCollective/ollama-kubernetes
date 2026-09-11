# Phase 5

I think this is going to be a throw away phase. It's about naming pods. I'll learn this, but I don't think this is the right approach for ollama. Rather I think we

- want a mapping of model sizes and pod sizes (redis key store or just looking up the model size in /api/tags)
- want a generic model pull job
- want an updated hpa that balances across pod sizes rather than model
