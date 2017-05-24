import os
from datetime import datetime
from collections import OrderedDict, defaultdict
import tempfile
import logging
import socket
import atexit
import signal
from flask import Flask, request, render_template, abort, make_response, redirect, url_for

app = Flask(__name__)

open_files = OrderedDict() # { task_key : file object }
log_paths = {}

statuses = defaultdict(lambda: StatusInfo(''))
last_msgs = defaultdict(lambda: '')

LOG_DIR = tempfile.mkdtemp()
MAX_OPEN_FILES = 100

LOG_MSG_FORMAT = "%(levelname)s %(asctime)s %(module)s %(process)d %(message)s"
#LOG_MSG_FORMAT = "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s"

FORMATTER = logging.Formatter(LOG_MSG_FORMAT)

class StatusInfo(object):
    def __init__(self, msg):
        self.msg = msg
        self.timestamp = datetime.now()
    
    def __str__(self):
        duration_minutes = (datetime.now() - self.timestamp).seconds // 60
        return '[{}] [{}m] {}'.format( self.timestamp.strftime('%H:%M'),
                                       duration_minutes,
                                       self.msg )

def get_log_file(task_key):
    """
    Returns a file handle for the given task_key, creating a new file if necessary.
    Manages the rotating LRU cache of open file handles, in case too many files are opened simultaneously.
    
    Note: The returned file handle will only be valid temporarily.
          You're not allowed to store it for future use.
    """
    if task_key in open_files:
        # Move to the end of the OrderedDict and return
        f = open_files[task_key]
        del open_files[task_key]
        open_files[task_key] = f
        return f

    # If we've already opened too many files, close some and discard them
    while len(open_files) >= MAX_OPEN_FILES:
        oldest_key = open_files.keys()[0]
        oldest_file = open_files[oldest_key]
        del open_files[oldest_key]
        oldest_file.flush()
        oldest_file.close()
    
    # Have we opened this file before?
    if task_key in log_paths:
        # Yes: Append.
        f = open(log_paths[task_key], 'a+')
    else:
        # No: Overwrite.
        log_path = os.path.join(LOG_DIR, task_key) + '.log'
        log_paths[task_key] = log_path

        f = open(log_path, 'w+')

    open_files[task_key] = f
    return f


@app.route('/logsink', methods=['POST'])
def receive_log_msg():
    task_key = request.form['task_key']
    assert isinstance(task_key, basestring), \
        "task_key must be a string"
    
    f = get_log_file(task_key)
    
    log_record = logging.LogRecord( request.form['name'],
                                    int(request.form['levelno']),
                                    request.form['pathname'],
                                    int(request.form['lineno']),
                                    request.form['msg'],
                                    eval(request.form['args']),
                                    exc_info=None,
                                    func=request.form['funcName'] )
    
    formatted_record = FORMATTER.format(log_record)
    f.write( formatted_record + "\n" )
    last_msgs[task_key] = formatted_record
    
    status = ''
    if 'status' in request.form:
        status = request.form['status']
    elif 'status=' in request.form['msg']:
        status_start = request.form['msg'].find('status=') + len('status=')
        status = request.form['msg'][status_start:]
    
    if status:
        statuses[task_key] = StatusInfo(status) 
    
    return ""

@app.route('/')
def index():
    return redirect(url_for('show_log_index'))

@app.route('/logs')
def show_log_index():
    column_names=['Task Name', 'Status', 'Last Msg']
    task_keys = sorted(log_paths.keys())
    task_tuples = [(k, statuses[k], last_msgs[k]) for k in task_keys]
    return render_template('logs.html.jinja',
                           hostname=socket.gethostname(),
                           log_dir=LOG_DIR,
                           task_tuples=task_tuples,
                           column_names=column_names)

@app.route('/logs/<task_key>')
def show_log(task_key):
    try:
        f = get_log_file(task_key)
        f.flush()
    except KeyError:
        abort(404)
    
    f.seek(0)
    response = make_response(f.read())
    response.headers['Content-Type'] = 'text/plain'
    return response

@app.route('/logs/flush', methods=['POST'])
def flush():
    flush_all()
    return redirect(url_for('show_log_index'))

def flush_all():
    for f in open_files.values():
        f.flush()

if __name__ == '__main__':
    import argparse
    import sys
    print sys.argv

    # Don't log ordinary GET, POST, etc.
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', default=3000)
    parser.add_argument('--log-dir', default=LOG_DIR)
    parser.add_argument('--max-open-files', default=100)
    parser.add_argument('--debug-mode', action='store_true')
    args = parser.parse_args()
    
    LOG_DIR = args.log_dir
    MAX_OPEN_FILES = args.max_open_files

    atexit.register(flush_all)
    
    # Terminate results in normal shutdown
    signal.signal(signal.SIGTERM, lambda signum, stack_frame: exit(1))
    
    print "Starting server on 0.0.0.0:{}".format(args.port)
    print "Saving logs to {}".format( LOG_DIR )
    app.run(host='0.0.0.0', port=args.port, debug=args.debug_mode)
