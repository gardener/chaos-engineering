def norm_filters(filters, expected_keys, tolerated_keys, empty_filter):
    if filters == None:
        filters = {}
    unexpected_keys = set(filters.keys()) - set(expected_keys) - set(tolerated_keys)
    if unexpected_keys:
        raise ValueError(f'Found unexpected filters for ' + ', '.join(unexpected_keys) + ' (expected filters are {expected_keys})!')
    for expected_key in expected_keys:
        if expected_key not in filters:
            filters[expected_key] = empty_filter
    return filters

def validate_duration(duration):
    if duration == None:
        duration = 0
    int(duration) # test that it can be casted to an int

def validate_mode(mode, supported_modes):
    if mode not in supported_modes:
        raise ValueError(f'Mode {mode} unsupported (supported modes are {supported_modes})!')

def validate_zone(zone):
    if not zone:
        raise ValueError(f'Zone not set (must be set)!')
