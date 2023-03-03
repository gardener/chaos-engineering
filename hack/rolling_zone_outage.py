import os.path
import sys
import time
import traceback

import logzero
from box import Box
from logzero import logfile, logger, loglevel

from chaosgarden.garden.actions import (
    assess_cloud_provider_filters_impact,
    run_cloud_provider_network_failure_simulation_in_background)
from chaosgarden.garden.probes import \
    run_shoot_cluster_health_probe_in_background
from chaosgarden.util.threading import terminate_all_threads, terminate_thread

if __name__ == '__main__':
    # configure logging
    loglevel(logzero.INFO)
    logfile("rolling_zone_outage.log", loglevel = logzero.DEBUG)

    # read configuration
    seed_config  = Box({
        'garden_project': 'garden',
        'garden_shoot':   os.getenv('GARDEN_SEED')})
    seed_node_monitor_grace_period = 120
    seed_unreachable_toleration_seconds = 300
    seed_machine_health_timeout = 1200
    shoot_config = Box({
        'garden_project': os.getenv('GARDEN_PROJECT'),
        'garden_shoot':   os.getenv('GARDEN_SHOOT')})
    shoot_node_monitor_grace_period = 15
    shoot_unreachable_toleration_seconds = 0
    shoot_machine_health_timeout = 120
    print(f'Please confirm running a rolling zone outage against:')
    print(f'- Seed:  {seed_config.garden_project}/{seed_config.garden_shoot}')
    print(f'- Shoot: {shoot_config.garden_project}/{shoot_config.garden_shoot}')
    reply = input('Press `Y` to continue...')
    if not reply or reply.lower()[0] != 'y':
        print(f'No confirmation. Aborting now.')
        sys.exit(0)
    reply = None

    # safeguard chaos experiments
    try:
        # define timespans
        quiet    = 60 # it may take up to 1m for the probe to be fully active
        duration = max(seed_node_monitor_grace_period + seed_unreachable_toleration_seconds,
                       shoot_node_monitor_grace_period + shoot_unreachable_toleration_seconds) + \
                   60 # total duration of outage; if below machine_health_timeout, machines will be kept, otherwise replaced
        cooldown = 600 if duration > min(seed_machine_health_timeout, shoot_machine_health_timeout) else 0 + \
                   120 # cooldown after outage; if the outage did not replace machines, 2m is sufficient (or more if in exponential back-off), otherwise add machine creation time (or more if in exponential back-off)

        # run simulation(s)
        for zone in range(0, 3): # strike each zone (exactly) once with the purpose to strike any leader/replica (at least) once
            # assess impacted resources and wait for confirmation
            assess_cloud_provider_filters_impact(zone = zone, configuration = seed_config)
            assess_cloud_provider_filters_impact(zone = zone, configuration = shoot_config)
            if reply == None:
                reply = input('Press `Y` to continue (only asked for the first zone and then not anymore)...')
                if not reply or reply.lower()[0] != 'y':
                    print(f'No confirmation. Aborting now.')
                    sys.exit(0)

            # define rough sensible thresholds (what can be expected at best, given the configuration of the tested clusters)
            kcm_ccm_kproxy_update_toleration = 15         # rough guess
            lb_dns_record_update_and_ttl_toleration = 180 # rough guess 2m for e.g. AWS to update the multi-zonal LB DNS record and 1m TTL for the DNS record itself
            node_monitor_period = 5                       # default, usually not changed
            regular_pod_recovery_toleration = 30          # rough guess
            outage_pod_recovery_toleration = duration + node_monitor_period + regular_pod_recovery_toleration
            api_server_recovery_toleration = seed_node_monitor_grace_period + kcm_ccm_kproxy_update_toleration + lb_dns_record_update_and_ttl_toleration
            thresholds = {
                'regional': { # tolerations for regional probes
                    'api': api_server_recovery_toleration,
                    'web-hook': api_server_recovery_toleration},
                f'{zone}': {  # tolerations for zonal probes in the zone that is under outage
                    'api-external': outage_pod_recovery_toleration,
                    'api-internal': outage_pod_recovery_toleration,
                    'dns-external': outage_pod_recovery_toleration,
                    'dns-internal': outage_pod_recovery_toleration,
                    'dns-management': outage_pod_recovery_toleration + 60,
                    'pod-lifecycle': outage_pod_recovery_toleration},
                f'!{zone}': { # tolerations for zonal probes in the zones that are not under outage
                    'api-external': api_server_recovery_toleration,
                    'api-internal': api_server_recovery_toleration,
                    'dns-external': 15,
                    'dns-internal': 15,
                    'dns-management': api_server_recovery_toleration + 60,
                    'pod-lifecycle': api_server_recovery_toleration + regular_pod_recovery_toleration}}

            # launch shoot cluster health probe in background and give it some quiet time to start and observe what's normal
            health_probe = run_shoot_cluster_health_probe_in_background(thresholds = thresholds, duration = -1, configuration = shoot_config)
            time.sleep(quiet)

            # launch simulation on seed and shoot in background parallelly
            seed_failure_simulation  = run_cloud_provider_network_failure_simulation_in_background(mode = 'total', zone = zone, duration = duration, configuration = seed_config)
            shoot_failure_simulation = run_cloud_provider_network_failure_simulation_in_background(mode = 'total', zone = zone, duration = duration, configuration = shoot_config)

            # wait for simulation on seed and shoot to end and give both some time to cool down and go back to what's normal
            seed_failure_simulation.join()
            shoot_failure_simulation.join()
            time.sleep(cooldown)

            # terminate shoot cluster health probe and evaluate report
            terminate_thread(health_probe)
    except Exception as e:
        logger.fatal(f'{e.__class__.__name__}: {type(e)}: {e}')
        print(traceback.format_exc(), end = '')
        logger.info(f'Experiments failed. Aborting now.')
        terminate_all_threads()
