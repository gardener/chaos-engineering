#!/bin/bash -e

rm "$(dirname "$0")/../chaostoolkit.log" | true
PYTHONPATH="$(dirname "$0")/.." chaos run --rollback-strategy always "$(dirname "$0")/experiments/${1%.json}.json"
