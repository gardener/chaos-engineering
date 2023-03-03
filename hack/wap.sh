#!/bin/bash -e

function show_resources() {
  echo "$(date) on ${GARDEN_PROJECT}/${GARDEN_SHOOT} shoot (focus on probe)"
  echo
  kubectl get nodes -L worker.gardener.cloud/pool,node.kubernetes.io/instance-type,kubernetes.io/arch,topology.kubernetes.io/zone
  echo
  kubectl -n chaos-garden-probe get pod -l 'chaos.gardener.cloud/role in (probe, probe-suicidal-pods, repl)' -o wide
  echo
  kubectl -n chaos-garden-probe get service,ep -o wide
  echo
  echo "NAME                                            READY    PAYLOAD"
  kubectl get hb --sort-by={metadata.creationTimestamp} --no-headers -o=custom-columns='NAME:.metadata.name,READY:.ready,PAYLOAD:.payload' | tac | head -21   # last 3 x 7 probes
  echo
  echo "NAME                            READY   PAYLOAD"
  kubectl get ahb --sort-by={metadata.creationTimestamp} --no-headers -o=custom-columns='NAME:.metadata.name,READY:.ready,PAYLOAD:.payload' | tac | head -9   # last 3 x 3 zones
}
export -f show_resources

watch --interval 0 --differences --color --no-title -- show_resources
