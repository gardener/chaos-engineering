#!/bin/bash -e

PYTHONPATH="$(dirname "$0")/.." python "$(dirname "$0")/rolling_zone_outage.py"
