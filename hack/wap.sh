#!/bin/bash -e

function filter_hbs_for() {
  echo
  echo "$1" | head -1
  echo "$1" | grep -E "$2" | tac | head -3
}
export -f filter_hbs_for

function show_resources() {
  echo "$(date) on ${GARDEN_PROJECT}/${GARDEN_SHOOT} shoot (focus on probe)"
  echo
  kubectl get nodes -L worker.gardener.cloud/pool,node.kubernetes.io/instance-type,kubernetes.io/arch,topology.kubernetes.io/zone
  echo
  kubectl -n chaos-garden-probe get pod -l 'chaos.gardener.cloud/role in (probe, probe-suicidal-pods, repl)' -o wide
  echo
  kubectl -n chaos-garden-probe get service,ep -o wide

  hbs=$(kubectl get hb --sort-by={metadata.creationTimestamp} -o=custom-columns='NAME:.metadata.name,READY:.ready,PAYLOAD:.payload' 2>&1)
  if echo $hbs | grep -q -F "Error from server (NotFound)"; then
    echo
    echo "No heartbeats found."
  else
    filter_hbs_for "$hbs" "^api-probe-regional-.*"
    filter_hbs_for "$hbs" "^api-external-probe-.*"
    filter_hbs_for "$hbs" "^api-internal-probe-.*"
    filter_hbs_for "$hbs" "^dns-external-probe-.*"
    filter_hbs_for "$hbs" "^dns-internal-probe-.*"
    filter_hbs_for "$hbs" "^dns-management-probe-.*"
    filter_hbs_for "$hbs" "^pod-lifecycle-probe-.*"
  fi

  hbs=$(kubectl get ahb --sort-by={metadata.creationTimestamp} -o=custom-columns='NAME:.metadata.name,READY:.ready,PAYLOAD:.payload' 2>&1)
  if echo $hbs | grep -q -F "Error from server (NotFound)"; then
    echo
    echo "No ack heartbeats found."
  else
    filter_hbs_for "$hbs" "^web-hook-probe-regional-.*"
  fi
}
export -f show_resources

watch --interval 0 --differences --color --no-title -- show_resources
