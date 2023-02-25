#!/bin/bash -e

function show_resources() {
  echo "$(date) on ${GARDEN_PROJECT}/${GARDEN_SHOOT} seed (focus on machines)"
  echo
  kubectl get machinedeployment,machineset,machine -L node
}
export -f show_resources

watch --interval 0 --differences --color --no-title -- show_resources
