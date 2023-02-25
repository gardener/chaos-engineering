#!/bin/bash -e

function show_resources() {
  echo "$(date) on ${GARDEN_PROJECT}/${GARDEN_SHOOT} shoot (focus on cluster)"
  echo
  kubectl get nodes -L worker.gardener.cloud/pool,node.kubernetes.io/instance-type,kubernetes.io/arch,topology.kubernetes.io/zone
  echo
  kubectl get ep,lease --all-namespaces
  echo
  kubectl get pod --all-namespaces -o wide
}
export -f show_resources

watch --interval 0 --differences --color --no-title -- show_resources
