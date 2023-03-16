import signal
import sys
import traceback
from datetime import datetime
from threading import Lock, Thread, current_thread, enumerate
from typing import Dict

from logzero import logger

__lock = Lock()
__threads : Dict[Thread, bool] = {}
__in_termination = False


def is_terminated(thread):
    with __lock:
        try:
            return __threads[thread]
        except KeyError:
            return __in_termination

def launch_thread(target, name = None, args = (), kwargs = None) -> Thread:
    with __lock:
        if __in_termination:
            return None
        thread = Thread(target = target, name = name if name else target.__name__, args = args, kwargs = kwargs)
        logger.info(f'Launching background thread {thread.name}.')
        __threads[thread] = False
        thread.start()
        return thread

def terminate_thread(thread):
    with __lock:
        try:
            __threads[thread] = True
        except KeyError:
            pass
    thread.join()
    with __lock:
        try:
            del __threads[thread]
        except KeyError:
            pass

def terminate_all_threads():
    global __in_termination
    with __lock:
        logger.info(f'Looking for still active background threads. Signaling and joining all {len(__threads)} active background threads.')
        if not __in_termination:
            __in_termination = True
        else:
            for thread in enumerate():
                if thread != current_thread():
                    logger.info(f'Still active background thread: {thread}')
                    traceback.print_stack(sys._current_frames()[thread.ident])
    while True:
        try:
            with __lock:
                threads = list(__threads.keys())
                for thread in threads: # shutdown performance optimization: signal all threads in batch before we join them one by one
                    __threads[thread] = True
            for thread in threads:
                logger.info(f'Waiting for background thread {thread.name} to end.')
                terminate_thread(thread)
            logger.info(f'Shutdown completed. All background threads terminated at {current_time()} (main thread must terminate on its own accord).')
            return
        except Exception as e:
            logger.error(f'Shutdown failed: {type(e)}: {e}')
            logger.error(traceback.format_exc())

def install_signal_handlers():
    logger.info(f'Installing signal handlers to terminate all active background threads on involuntary signals (note that SIGKILL cannot be handled).')
    signal.signal(signal.SIGTERM, signal_handler_called)
    signal.signal(signal.SIGQUIT, signal_handler_called)
    signal.signal(signal.SIGINT, signal_handler_called)

def signal_handler_called(signal_number = None, stack_frame = None): # signature implements signal.signal() handler interface
    if not __in_termination:
        logger.info(f'Signal handler invoked ({signal.Signals(signal_number).name}). Aborting now.')
        terminate_all_threads()

def current_time():
    return datetime.now().strftime('%H:%M:%S')
