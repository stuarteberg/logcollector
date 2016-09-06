import os
from datetime import datetime
import tempfile
import logging
import socket
import atexit
import signal
from flask import Flask, request, render_template, abort, make_response, redirect, url_for

app = Flask(__name__)

log_files = {} # { task_key : file object }
statuses = {}
last_msgs = {}

LOG_DIR = tempfile.mkdtemp()

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

@app.route('/logsink', methods=['POST'])
def receive_log_msg():
    task_key = request.form['task_key']
    assert isinstance(task_key, basestring), \
        "task_key must be a string"
    
    try:
        f = log_files[task_key]
    except KeyError:
        log_path = os.path.join(LOG_DIR, task_key) + '.log'
        f = open(log_path, 'w+')
        log_files[task_key] = f
        statuses[task_key] = ''
        last_msgs[task_key] = ''
    
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
    task_keys = sorted(log_files.keys())
    task_tuples = [(k, statuses[k], last_msgs[k]) for k in task_keys]
    return render_template('logs.html.jinja',
                           hostname=socket.gethostname(),
                           log_dir=LOG_DIR,
                           task_tuples=task_tuples,
                           column_names=column_names)

@app.route('/logs/<task_key>')
def show_log(task_key):
    try:
        f = log_files[task_key]
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
    for f in log_files.values():
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
    parser.add_argument('--debug-mode', action='store_true')
    args = parser.parse_args()
    
    LOG_DIR = args.log_dir

    atexit.register(flush_all)
    
    # Terminate results in normal shutdown
    signal.signal(signal.SIGTERM, lambda signum, stack_frame: exit(1))
    
    print "Starting server on 0.0.0.0:{}".format(args.port)
    print "Saving logs to {}".format( LOG_DIR )
    app.run(host='0.0.0.0', port=args.port, debug=args.debug_mode)
