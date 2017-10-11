import logging
import threading
from functools import partial, wraps
from logging.handlers import HTTPHandler

def get_localhost_ip_address():
    """
    Return this machine's own IP address, as seen from the network
    (e.g. 192.168.1.152, not 127.0.0.1)
    """
    import socket
    try:
        # Determine our own machine's IP address
        # This method is a little hacky because it requires
        # making a connection to some arbitrary external site,
        # but it seems to be more reliable than the method below. 
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("google.com",80))
        ip_addr = s.getsockname()[0]
        s.close()
        
    except socket.gaierror:
        # Warning: This method is simpler, but unreliable on some networks.
        #          For example, on a home Verizon FiOS network it will error out in the best case,
        #          or return the wrong IP in the worst case (if you haven't disabled their DNS
        #          hijacking on your router)
        ip_addr = socket.gethostbyname(socket.gethostname())
    
    return ip_addr

localhost_ip = get_localhost_ip_address()

class HTTPHandlerWithExtraData(HTTPHandler):
    """
    Simple subclass of HTTPHandler that adds extra
    fields to the LogRecord before sending it.
    The fields are specified upon construction.
    """
    def __init__(self, extra_data, host, url, method='GET'):
        host = host.split('://')[-1]
        if ':' in host:
            host, port = host.split(':')
        else:
            port = None

        if host == localhost_ip:
            # If we're logging to our own machine (e.g. during testing),
            # it's more reliable under various network environments to use 0.0.0.0
            # (Things get weird if you're using a VPN, for instance.)
            host = '0.0.0.0'

        if port:
            fullhost = '0.0.0.0:{}'.format(port)
        else:
            fullhost = host

        super(HTTPHandlerWithExtraData, self).__init__(fullhost, url, method)
        self.extra_data = extra_data

    def emit(self, record):
        super().emit(record)

    def mapLogRecord(self, record):
        record.__dict__.update(self.extra_data)
        return record.__dict__

try:
    import requests
except ImportError:
    pass
else:
    class JSONHttpHandler(logging.Handler):
        """
        Just like the above HTTPHandlerWithExtraData, but info is sent via
        json data in the request body instead of via a 'form'.
        (The logserver accepts either format.)
        """
        def __init__(self, extra_data, host, url, method='POST'):
            super().__init__()

            host = host.split('://')[-1]
            if ':' in host:
                host, port = host.split(':')
            else:
                port = None
    
            if host == localhost_ip:
                # If we're logging to our own machine (e.g. during testing),
                # it's more reliable under various network environments to use 0.0.0.0
                # (Things get weird if you're using a VPN, for instance.)
                host = '0.0.0.0'
    
            if port:
                fullhost = '0.0.0.0:{}'.format(port)
            else:
                fullhost = host

            self.method = method
            self.extra_data = extra_data
            self.host = fullhost
            self.url = url
            
            if not self.host.startswith('http://'):
                self.host = 'http://' + self.host
            
        def emit(self, record):
            try:
                data = { 'name': record.name,
                         'levelno': record.levelno,
                         'pathname': record.pathname,
                         'lineno' : record.lineno,
                         'msg': record.msg,
                         'args': repr(record.args),
                         'exc_info': None,
                         'funcName': record.funcName}
        
                data.update(self.extra_data)
        
                requests.request(self.method, self.host + self.url, json=data )
            except Exception:
                self.handleError(record)

class LoggingThreadFilter(logging.Filter):
    """
    A logging filter that accepts only those messages which are emitted
    within the same thread as the one that created this filter.
    """
    def __init__(self):
        self.thread_ident = threading.current_thread().ident
    
    def filter(self, record):
        return (threading.current_thread().ident == self.thread_ident)

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
            thread_filter = LoggingThreadFilter()
            handler = handler_factory(*args, **kwargs)
            handler.addFilter(thread_filter)
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

def noop_decorator(func):
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper
