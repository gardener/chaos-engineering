#!/bin/bash -e

kubectl -n default delete --force=true --grace-period=0 pod repl 2> /dev/null || true
