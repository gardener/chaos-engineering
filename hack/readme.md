# Hack

## Purpose

This is a collection of scripts and resources that helps with local development.

## Index

- `chaos.sh`: Run experiment in [`/hack/experiments`](/hack/experiments) specified by name with `chaostoolkit` CLI using local sources
- `experiments`: Folder with experiments:
  - `compute.json`: Run compute failure simulation with prior assessment/confirmation
  - `network.json`: Run network failure simulation with prior assessment/confirmation
  - `probe.json`: Launch cluster health probe
- `logs.sh`: Show logs of cluster health probe pods
- `readme.md`: This document
- `repl_deploy.sh`: Deploy a Python pod into a cluster to try out operations from within the cluster
- `repl_delete.sh`: Delete the above
- `repl_resources.yaml`: Resources for the above
- `repl_bash.sh`: Exec into the above pod and run `bash` interactive shell
- `repl.sh`: Exec into the above pod and run Python interactive shell
- `rolling_zone_outage.sh`: Perform a rolling zone outage on a seed and shoot in parallel
- `rolling_zone_outage.py`: Source code for above
- `wap`: Watch cluster health probe resources (target shoot manually first)
- `wacl`: Watch key cluster resources (target shoot manually first)
- `wacp`: Watch key control plane resources (target seed manually first)
- `wama`: Watch key machine resources (target seed manually first)
