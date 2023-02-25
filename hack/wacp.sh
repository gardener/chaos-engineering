#!/bin/bash -e

function show_resources() {
  echo "$(date) on ${GARDEN_PROJECT}/${GARDEN_SHOOT} seed (focus on control plane)"
  echo
  kubectl get nodes -L worker.gardener.cloud/pool,node.kubernetes.io/instance-type,kubernetes.io/arch,topology.kubernetes.io/zone
  echo
  for ns in $(kubectl get ns | grep -F 'istio-ingress--' | awk '{print $1}' | sort); do
    echo
    echo ZONE $ns
    kubectl -n $ns get pods,ep -o wide
  done
  echo
  kubectl get ep,lease
  echo
  kubectl get etcd -o=custom-columns='NAME:.metadata.name,DESIRED_REPLICAS:.status.clusterSize,ACTUAL_REPLICAS:.status.replicas,READY_REPLICAS:.status.readyReplicas,OVERALL_READY_STATUS:.status.ready,READY:.status.conditions[?(@.type=="AllMembersReady")].status,BACKUP:.status.conditions[?(@.type=="BackupReady")].status,QUOROM:.status.conditions[?(@.type=="Ready")].status'
  echo
  kubectl get pod -l gardener.cloud/role=controlplane -o wide
}
export -f show_resources

watch --interval 0 --differences --color --no-title -- show_resources
