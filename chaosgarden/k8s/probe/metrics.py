import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from functools import reduce
from typing import Dict, List, Tuple

from logzero import logger

from chaosgarden.k8s.probe.thresholds import Thresholds

INITIAL_FAILURE_EXCLUSION = defaultdict(lambda: 0, **{
    'dns-management': 60,
    'web-hook': 50})
INITIAL_GAP_TOLERATION = defaultdict(lambda: 30, **{
    'api': 15,
    'api-external': 30,
    'api-internal': 30,
    'dns-external': 30,
    'dns-internal': 30,
    'dns-management': 60,
    'pod-lifecycle': 40,
    'web-hook': 50})
REGULAR_GAP_TOLERATION = defaultdict(lambda: 15, **{
    'api': 15,
    'api-external': 15,
    'api-internal': 15,
    'dns-external': 15,
    'dns-internal': 15,
    'dns-management': 30,
    'pod-lifecycle': 30,
    'web-hook': 30})


class HeartbeatState(Enum):
    READY = 'Ready'
    NOT_READY = 'NotReady'
    UNKNOWN = 'Unknown' # a.k.a. gap, inserted when we did not receive a heartbeat in time


class HeartbeatStateSeries:
    def __init__(self, probe: str):
        self._probe: str = probe
        self._series: Dict[int, Tuple[HeartbeatState, str]] = {}
        self._gaps = 0

    def __iter__(self):
        return iter(sorted(self._series.items()))

    def record(self, timestamp: int, ready: HeartbeatState, payload: str = None):
        self._series[timestamp] = (ready, payload)
        if ready == HeartbeatState.UNKNOWN:
            self._gaps += 1

    def drop(self, timestamp: int):
        return self._series.pop(timestamp, None)

    def get_timestamps(self, from_timestamp: int = 0, to_timestamp: int = sys.maxsize):
        return sorted([timestamp for timestamp in self._series.keys() if timestamp >= from_timestamp and timestamp < to_timestamp])

    def get_state(self, timestamp):
        return self._series[timestamp][0]

    def get_gaps(self):
        return self._gaps

    def compute(self, from_timestamp: int, to_timestamp: int):
        # drop failed heartbeats until state changes for the first time or grace period ends
        # (happens e.g. with web hook acknowledged heartbeats that are reporting `False` until
        #  the web hook becomes active; we don't care and don't want to see those heartbeats)
        for timestamp in self.get_timestamps(to_timestamp = from_timestamp + max(0, INITIAL_FAILURE_EXCLUSION[self._probe])):
            if self.get_state(timestamp) == HeartbeatState.NOT_READY:
                self.drop(timestamp)
            else:
                break

        # get (default) tolerated initial and regular gaps before/in between individual heartbeats, so that we know when to insert gap heartbeats indicating loss of heartbeat
        initial_gap = max(0, INITIAL_GAP_TOLERATION[self._probe])
        regular_gap = max(1, REGULAR_GAP_TOLERATION[self._probe])

        # insert first and/or last gap heartbeat if missing
        timestamps = self.get_timestamps()
        if timestamps[0] > from_timestamp + initial_gap:
            self.record(from_timestamp + initial_gap, HeartbeatState.UNKNOWN, 'Gap (Initial)')
        if timestamps[-1] + regular_gap < to_timestamp:
            self.record(to_timestamp, HeartbeatState.UNKNOWN, 'Gap (Final)')

        # insert intermediate gap heartbeats if missing
        timestamps = self.get_timestamps()
        prev_timestamp = timestamps[0]
        for next_timestamp in timestamps[1:]:
            if next_timestamp > prev_timestamp + regular_gap:
                for timestamp in range(prev_timestamp + regular_gap, next_timestamp, regular_gap):
                    self.record(timestamp, HeartbeatState.UNKNOWN, 'Gap')
            prev_timestamp = next_timestamp

    def dump(self):
        for timestamp, (state, payload) in self:
            logger.debug(f'    - {state.value:>9} at {datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")}' + (f' ({payload})' if payload else ''))


@dataclass
class HeartbeatPhase:
    state: HeartbeatState
    duration: int


class HeartbeatPhaseSeries:
    def __init__(self, probe: str):
        self._probe: str = probe
        self._series: List[HeartbeatPhase] = []
        self._downtime: int = 0

    def __iter__(self):
        return iter(self._series)

    def get_probe_name(self):
        return self._probe

    def get_downtime(self):
        return self._downtime

    def compute(self, heartbeats: HeartbeatStateSeries):
        # replace stable individual states with phases with duration
        timestamps = heartbeats.get_timestamps()
        prev_timestamp = timestamps[0]
        prev_state = heartbeats.get_state(prev_timestamp)
        if len(timestamps) >= 2:
            for next_timestamp in timestamps[1:]:
                next_state = heartbeats.get_state(next_timestamp)
                if next_state != prev_state or next_timestamp == timestamps[-1]:
                    phase = HeartbeatPhase(prev_state, next_timestamp - prev_timestamp)
                    self._series.append(phase)
                    if prev_state != HeartbeatState.READY:
                        self._downtime  += phase.duration
                    prev_timestamp = next_timestamp
                    prev_state = next_state
        else:
            self._series.append(HeartbeatPhase(prev_state, 0))

    def dump(self):
        for phase in self:
            logger.info(f'    - {phase.state.value:>9} for {phase.duration:>4}s')


class MetricsForZone:
    def __init__(self, probe, zone):
        self._probe = probe
        self._zone = zone
        self._heartbeats = HeartbeatStateSeries(probe)
        self._heartbeats_sent = self._heartbeats_received = None
        self._phases = HeartbeatPhaseSeries(probe)

    def get_probe_name(self):
        return self._probe

    def get_zone_name(self):
        return self._zone

    def record_heartbeat(self, timestamp, ready, payload = None):
        self._heartbeats.record(timestamp, ready, payload)

    def record_heartbeats_sent(self, sent):
        self._heartbeats_sent = sent

    def get_heartbeats_sent(self):
        return self._heartbeats_sent

    def get_heartbeats_received(self):
        return self._heartbeats_received

    def get_heartbeats_gaps(self):
        return self._heartbeats.get_gaps()

    def get_heartbeats_lost(self):
        return self.get_heartbeats_sent() - self.get_heartbeats_received()

    def get_downtime(self):
        return self._phases.get_downtime()

    def compute(self, from_timestamp: int, to_timestamp: int):
        # record actual number of sent and received heartbeats (sent is assumed to be equal to received unless overwritten by setter function)
        self._heartbeats_received = len(self._heartbeats.get_timestamps()) if self._heartbeats_received == None else self._heartbeats_received
        self._heartbeats_sent = self._heartbeats_received if self._heartbeats_sent == None else self._heartbeats_sent

        # compute gap heartbeats
        self._heartbeats.compute(from_timestamp, to_timestamp)

        # compute contiguous phases
        self._phases.compute(self._heartbeats)

    def dump(self, thresholds: Thresholds):
        logger.info(f'  - Zone: {self.get_zone_name().upper()} ({self.get_heartbeats_sent()}x sent, {self.get_heartbeats_received()}x received, {self.get_heartbeats_gaps()}x gaps, {self.get_heartbeats_lost()}x lost, {self.get_downtime()}s total downtime and {thresholds.get_toleration(probe = self.get_probe_name(), zone = self.get_zone_name())}s maximum toleration)')
        self._phases.dump()
        logger.debug(f'    Records:')
        self._heartbeats.dump()

    def assess(self, thresholds: Thresholds):
        violations = []
        if self.get_heartbeats_lost() != 0:
            violations.append(f'Data loss detected: {self.get_heartbeats_sent()}x sent, {self.get_heartbeats_received()}x received, {self.get_heartbeats_lost()}x lost, which means we lost ETCD data!')
        if self.get_downtime() > thresholds.get_toleration(probe = self.get_probe_name(), zone = self.get_zone_name()):
            violations.append(f'Functional outage detected: {self.get_probe_name().upper()} in zone {self.get_zone_name().upper()} was {self.get_downtime()}s not Ready, but only {thresholds.get_toleration(probe = self.get_probe_name(), zone = self.get_zone_name())}s were tolerated, which means we missed KPI goals!')
        return violations


class MetricsForZoneCollection:
    def __init__(self, probe):
        self._probe = probe
        self._zones: Dict[str, MetricsForZone] = {}

    def __iter__(self):
        return iter(sorted(self._zones.values(), key = lambda x: x.get_zone_name()))

    def get_probe_name(self):
        return self._probe

    def get_metrics_for_zone(self, zone):
        return self._zones.setdefault(zone.lower(), MetricsForZone(self._probe, zone.lower()))

    def get_downtime(self):
        return reduce(lambda x, y: x + y, [m.get_downtime() for m in self._zones.values()], 0)

    def compute(self, from_timestamp: int, to_timestamp: int):
        for zone in self:
            zone.compute(from_timestamp, to_timestamp)

    def dump(self, thresholds: Thresholds):
        for m in self:
            m.dump(thresholds)

    def assess(self, thresholds: Thresholds):
        violations = []
        for m in self:
            violations.extend(m.assess(thresholds))
        return violations


class Metrics:
    def __init__(self, heartbeats: List[Dict], from_timestamp: int, to_timestamp: int):
        self._probes: Dict[str, MetricsForZoneCollection] = {}
        for heartbeat in heartbeats:
            segments = re.match(r'^(.+)-probe-(.+)-([0-9]+)', heartbeat['metadata']['name'].lower())
            probe, zone, timestamp = segments.group(1), segments.group(2), int(segments.group(3))
            if timestamp >= (from_timestamp - 5) and timestamp <= (to_timestamp + 15):
                self.get_metrics_for_probe(probe).get_metrics_for_zone(zone).record_heartbeat(timestamp, HeartbeatState.READY if heartbeat['ready'] else HeartbeatState.NOT_READY, heartbeat['payload'] if 'payload' in heartbeat and heartbeat['payload'] else None)
            else:
                pass # rejecting {probe} heartbeat from zone {zone} with timestamp {datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")}
        for probe in self:
            probe.compute(from_timestamp, to_timestamp)

    def __iter__(self):
        return iter(sorted(self._probes.values(), key = lambda x: x.get_probe_name()))

    def get_metrics_for_probe(self, probe):
        return self._probes.setdefault(probe.lower(), MetricsForZoneCollection(probe.lower()))

    def get_downtime(self):
        return reduce(lambda x, y: x + y, [m.get_downtime() for m in self._probes.values()], 0)

    def dump(self, thresholds: Thresholds):
        logger.info(f'Metrics:')
        for m in self:
            logger.info(f'- Probe:  {m.get_probe_name().upper()} ({m.get_downtime()}s total downtime)')
            m.dump(thresholds)

    def assess(self, thresholds: Thresholds):
        violations = []
        for m in self:
            violations.extend(m.assess(thresholds))
        return violations
