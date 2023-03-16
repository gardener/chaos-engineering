#!/bin/bash -e

kubectl -n chaos-garden-probe logs -f -l 'chaos.gardener.cloud/role in (probe, probe-suicidal-pods)' --max-log-requests 12