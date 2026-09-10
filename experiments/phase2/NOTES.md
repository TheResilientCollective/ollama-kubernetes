### 18 Aug

Just copied phase 1 into a new directory to mess around with phase 2.

### 8 Sept

Updated all the code. Noticed a problem where the containers don't appear to be pulling the ollama model so they never are marked as ready (the readiness probe appears to be working in that case)

I need to add in `spec.initContainers` to the deployment file. I believe this also requires reformatting the deployment file structure.

### 9 Sept

/bin/bash doesn't work in the ollama container. So pipefail commands don't work.
Also needed to make sure ollama server was running before pulling the model.

I also updated the `deployment.yaml` to have a `spec.strategy.type: Recreate` rather than the default `RollingUpdate` just to make things a little cleaner and more obvious to me when developing. This shouldn't be used in production code.
