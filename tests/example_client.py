import os
import sys
import time
import logging
import threading
from functools import partial
from logcollector.client_utils import make_log_collecting_decorator

def main():
    
    # logger name is not important; root logger (and above) is monitored.
    logger = logging.getLogger('simpletest')
    
    # logger level still matters as usual
    logger.setLevel(logging.INFO)
    
    # So we also see the output on the client console
    logger.addHandler(logging.StreamHandler(sys.stdout))
    

    SERVER = '127.0.0.1'
    PORT = 3000

    # Make a decorator with server and port already bound
    send_log_with_key = make_log_collecting_decorator(SERVER, PORT)
    
    @send_log_with_key(lambda task_key, *args, **kwargs: task_key)
    def do_some_stuff(task_key, other_param, other_param2):
        print "STARTING task {}...".format(task_key)
        N_MSG = 30
        for i in range(30):
            time.sleep(1.0)
            logger.info("Task {}:({}) Test message {}: with args: %s, %d".format(task_key, threading.current_thread().ident, i ),
                        'hi', 42, extra={'status': '{:.1f}'.format(100.*(i+1)/N_MSG)})
        print "DONE."

    threads = []
    for i in range(100):
        # Use i as the 'task_key'
        func = partial(do_some_stuff, '{:03d}'.format(i), 'foo', 'bar')
        threads.append(threading.Thread(target=func))

    for t in threads:
        t.start()
    
    for t in threads:
        t.join()

if __name__ == "__main__":
    main()
