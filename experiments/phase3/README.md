# Phase 3

I'm updating the planned phase3 to now be a shared PVC storage between the pods. This allows each new pod to load faster as it doesn't have to pull the ollama model from the internet. It just has to load into memory from shared storage.

This adds a small complication in that we need to make sure that the pods aren't all trying to read/write to the shared storage at the same time.
To get around this we create a job that handles pulling the model.
