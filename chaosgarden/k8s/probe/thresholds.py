from collections import defaultdict
from typing import Dict

DEFAULT_TOLERATION = 0
NEGATION_SYMBOL = '!'


class Thresholds:
    def __init__(self, thresholds: Dict[str, Dict[str, int]]):
        self._thresholds: Dict[str, Dict[str, int]] = defaultdict(dict) # maps zone selector to probe name to outage tolerations in seconds
        for zone_selector, tolerations in thresholds.items():
            for probe, toleration in tolerations.items():
                self._thresholds[zone_selector.lower()][probe.lower()] = int(toleration)

    @staticmethod
    def from_dict(thresholds: Dict[str, Dict[str, int]]):
        return Thresholds(thresholds)

    def to_dict(self):
        return dict(self._thresholds)

    def substitute_zones(self, zones: Dict[int, str]):
        _thresholds = {}
        for zone_selector, tolerations in self._thresholds.items():
            negated = zone_selector.startswith(NEGATION_SYMBOL)
            if negated:
                zone_selector = zone_selector[1:]
            try:
                _thresholds[f'{"!" if negated else ""}{zones[int(zone_selector)].lower()}'] = tolerations
            except:
                _thresholds[f'{"!" if negated else ""}{zone_selector}'] = tolerations
        self._thresholds = _thresholds
        return self

    def get_toleration(self, probe: str, zone: str):
        probe = probe.lower()
        zone = zone.lower()
        for zone_selector, tolerations in self._thresholds.items():
            if probe in tolerations:
                negated = zone_selector.startswith(NEGATION_SYMBOL)
                if negated and zone != zone_selector[1:]:
                    return tolerations[probe]
                if not negated and zone == zone_selector:
                    return tolerations[probe]
        return DEFAULT_TOLERATION

    def within_toleration(self, probe: str, zone: str, value: int):
        return value <= self.get_toleration(probe, zone)
