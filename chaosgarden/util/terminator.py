import inspect
from datetime import datetime, timedelta
from threading import current_thread, main_thread

from logzero import logger

from chaosgarden.util.threading import (current_time, install_signal_handlers,
                                        is_terminated)

# install signal handlers automatically when terminators are used (also critical with `chaostoolkit` CLI and background mode)
# to terminate all active threads on involuntary signals (note that SIGKILL cannot be handled)
install_signal_handlers()


class Terminator():
    def __init__(self, duration = 0):
        self._caller            = inspect.stack()[1].function
        self._duration          = int(duration)
        self._start_time        = datetime.now()
        self._end_time          = self._start_time + timedelta(seconds = self._duration) if self._duration > 0 else None
        self._invocations       = 0
        self._single_invocation = True if self._duration == 0 else False

    def _log_termination(self, reason):
        logger.info(f'{reason} for {current_thread().name if current_thread() != main_thread() else self._caller} at {current_time()} ({(datetime.now() - self._start_time).total_seconds():.1f}s net duration). Terminating now.')

    def is_terminated(self):
        single_invocation_performed = self._single_invocation and self._invocations == 1
        if single_invocation_performed:
            self._log_termination(f'Single invocation performed')
        time_is_up = self._end_time and datetime.now() > self._end_time
        if time_is_up:
            self._log_termination(f'Time is up')
        termination_requested = is_terminated(current_thread())
        if termination_requested:
            self._log_termination(f'Termination requested')
        self._invocations += 1
        return single_invocation_performed or time_is_up or termination_requested
