# Phase 7

Model-Routing Gateway

There's now a values-router.yaml which spawns the template chart/templates/router-\*.yaml

It has to be a template so that it can utilize the helm variables that determine the size of different pods.

Also, the pod sizes are now all concentrated in chart/values.yaml rather than in the values-<size>.yaml files. The values-<size>.yaml files still exist, they are just a single line to tell helm which values to use.
