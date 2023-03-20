import os
import sys

from chaosgarden.garden.actions import (
    assess_cloud_provider_filters_impact,
    run_cloud_provider_network_failure_simulation_in_background)

if __name__ == '__main__':
    # compose experiment configuration
    configuration = {
        'garden_project': os.getenv('GARDEN_PROJECT'),
        'garden_shoot':   os.getenv('GARDEN_SHOOT')}

    # print experiment configuration ask for confirmation
    print('Please confirm running a (double) zone outage against: ' +
        configuration['garden_project'] + '/' + configuration['garden_shoot'])
    reply = input('Press `Y` to continue... ')
    if not reply or reply.lower()[0] != 'y':
        print('No confirmation. Aborting now.')
        sys.exit(0)

    # assess cloud provider resources and ask for confirmation
    assess_cloud_provider_filters_impact(zone=0, configuration=configuration)
    assess_cloud_provider_filters_impact(zone=1, configuration=configuration)
    print('Please confirm running a (double) zone outage against the above resources.')
    reply = input('Press `Y` to continue... ')
    if not reply or reply.lower()[0] != 'y':
        print('No confirmation. Aborting now.')
        sys.exit(0)

    # launch simulations in parallel in background
    sim_zone_0_failure = run_cloud_provider_network_failure_simulation_in_background(
        zone=0, duration=120, configuration=configuration)
    sim_zone_1_failure = run_cloud_provider_network_failure_simulation_in_background(
        zone=1, duration=60, configuration=configuration)

    # wait for simulations to end and join threads of destruction
    sim_zone_0_failure.join()
    sim_zone_1_failure.join()
