#!/bin/bash -e

"$(dirname "$0")/repl_delete.sh"
kubectl -n default apply -f "$(dirname "$0")/repl_resources.yaml"
kubectl -n default get pods -o wide -w
