import logging
from logging.handlers import HTTPHandler
from functools import partial, wraps

class HTTPHandlerWithExtraData(HTTPHandler):
    """
    Simple subclass of HTTPHandler that adds extra
    fields to the LogRecord before sending it.
    The fields are specified upon construction.
    """
    def __init__(self, extra_data, host, url, method='GET'):
        super(HTTPHandlerWithExtraData, self).__init__(host, url, method)
        self.extra_data = extra_data

    def mapLogRecord(self, record):
        record.__dict__.update(self.extra_data)
        return record.__dict__

def logging_context(handler_factory=lambda *args, **kwargs: logging.StreamHandler()):
    """
    Returns a decorator.
    
    While the decorated function is running, a logging handler
    is created and activated on the root logger.
    
    The logging handler is created using the given handler_factory.
    The arguments to the decorated function are also passed to handler_factory,
    in case they are useful for parameterizing the handler. 
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            handler = handler_factory(*args, **kwargs)
            logging.getLogger().addHandler(handler)
            try:
                return func(*args, **kwargs)
            finally:
                logging.getLogger().removeHandler(handler)
        
        wrapper.__wrapped__ = func # Emulate python 3 behavior of @functools.wraps
        return wrapper
    return decorator

def log_collecting_context(server, port, task_key_factory=lambda *args, **kwargs: args[0]):
    """
    Returns a decorator.
    
    Same as logging_context(), but implements a handler_factory
    that always creates instances of HTTPHandlerWithExtraData.
    """
    def create_handler(*args, **kwargs):
        return HTTPHandlerWithExtraData(
            { 'task_key': task_key_factory(*args, **kwargs) },
            "{}:{}".format(server, port),
            '/logsink',
            'POST' )
    return logging_context(create_handler)

def make_log_collecting_decorator( server, port ):
    """
    Returns the log_collecting_context function from above,
    but with pre-configured server and port.
    
    Exmaple:
    
        # Make a decorator with pre-configured server/port
        send_log_with_key = make_log_collecting_decorator('127.0.0.1', 3000)
    
        # Use the decorator on functions whose logs
        # you want sent to the logcollector server.
        @send_log_with_key(lambda task_key, foo, bar: task_key)
        def my_processing_function(task_key, foo, bar):
            bla bla bla

        @send_log_with_key(lambda task_key, foo, bar: task_key)
        def my_processing_function2(task_key, foo, bar):
            bla bla bla    
    """
    return partial(log_collecting_context, server, port)
