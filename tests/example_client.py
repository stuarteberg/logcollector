import os
import time
import logging
from logcollector.client_utils import make_log_collecting_decorator

def main():
    
    # logger name is not important; root logger (and above) is monitored.
    logger = logging.getLogger('simpletest')
    
    # logger level still matters as usual
    logger.setLevel(logging.INFO)
    

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
            logger.info("Test message {}: with args: %s, %d".format( i ), 'hi', 42, extra={'progress': 100.*(i+1)/N_MSG})
        print "DONE."

    # For this example, use the PID as the 'task_key'
    do_some_stuff( os.getpid(), 'foo', 'bar' )

if __name__ == "__main__":
    main()
