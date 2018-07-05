from __future__ import print_function
import sys
import os
import time
from datetime import datetime
from collections import OrderedDict, defaultdict
import tempfile
import traceback
import logging
import socket
import signal
from flask import Flask, request, render_template, abort, make_response, redirect, url_for

if sys.version_info.major > 2:
    unicode = str

app = Flask(__name__)

open_files = OrderedDict() # { task_key : file object }
log_paths = {}

statuses = defaultdict(lambda: StatusInfo(''))
last_msgs = defaultdict(lambda: '')

LOG_DIR = tempfile.mkdtemp()
MAX_OPEN_FILES = 100

DEFAULT_LOG_MSG_FORMAT = '%(levelname)s [%(asctime)s] %(message)s'
#DEFAULT_LOG_MSG_FORMAT = "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s"

FORMATTER = logging.Formatter(DEFAULT_LOG_MSG_FORMAT)

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
        oldest_key = next(iter(open_files.keys()))
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
    if request.json:
        data = request.json
    else:
        data = request.form

    task_key = data['task_key']
    assert isinstance(task_key, (bytes, unicode)), \
        "task_key must be a string, not {}".format(type(task_key))
    
    f = get_log_file(task_key)
    
    try:
        args = eval(data['args'])
    except:
        args = ['<<logcollector.logserver.receive_log_msg: Could not interpret args>>']
    
    log_record = logging.LogRecord( data['name'],
                                    int(data['levelno']),
                                    data['pathname'],
                                    int(data['lineno']),
                                    data['msg'],
                                    args,
                                    exc_info=None,
                                    func=data['funcName'] )
    
    formatted_record = FORMATTER.format(log_record)
    f.write( formatted_record + "\n" )

    # When the child logs a message, this flag tells us to echo the message
    # onto the console in addition to writing it to the appropriate file.
    if data['echo_on_console'] in (True, 'true', 'True'):
        sys.stdout.write(formatted_record + "\n")
    
    last_msgs[task_key] = formatted_record
    
    status = ''
    if 'status' in data:
        status = data['status']
    elif 'status=' in data['msg']:
        status_start = data['msg'].find('status=') + len('status=')
        status = data['msg'][status_start:]
    
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
    close_all()
    return redirect(url_for('show_log_index'))

def flush_all():
    for f in open_files.values():
        f.flush()

def close_all():
    global open_files
    _open_files = open_files
    open_files = OrderedDict()

    for f in _open_files.values():
        f.close()

def shutdown_server():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()

@app.route('/shutdown', methods=['POST'])
def shutdown():
    shutdown_server()
    close_all()
    return 'Server shutting down...'

##
## ECLIPSE DEBUGGING CODE
##
def connect_debugger():
    import sys
    import os
    
    # Possible paths to the pydev debugger module on your hard drive.
    # Developers: Add your dev machine's pydev directory to this list.
    pydev_src_paths = [ "/Applications/eclipse/plugins/org.python.pydev_4.5.5.201603221110/pysrc/",
                        "/usr/local/eclipse/plugins/org.python.pydev_4.2.0.201507041133/pysrc/",
                        '/Users/bergs/.p2/pool/plugins/org.python.pydev_5.5.0.201701191708/pysrc/' ]

    pydev_src_paths = list(filter(os.path.exists, pydev_src_paths))
    
    if not pydev_src_paths:
        raise RuntimeError("Error: Couldn't find the path to the pydev module.  You can't use PYDEV_DEBUGGER_ENABLED.")
    
    if len(pydev_src_paths) > 1:
        raise RuntimeError("Error: I found more than one pydev module.  I don't know which one to use.")
    
    sys.path.append(pydev_src_paths[0])
    import pydevd
    print("Waiting for PyDev debugger...")
    pydevd.settrace(stdoutToServer=True, stderrToServer=True, suspend=False)

if int(os.getenv('PYDEV_DEBUGGER_ENABLED', 0)):
    connect_debugger()

##
##
##


if __name__ == '__main__':
    import argparse
    import sys
    print(sys.argv)

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
    # Terminate results in normal shutdown
    signal.signal(signal.SIGTERM, lambda signum, stack_frame: exit(1))
    
    print("Starting server on 0.0.0.0:{}".format(args.port))
    print("Saving logs to {}".format( LOG_DIR ))

    # Auto-restart the server if it fails for some socket-related reason
    while True:
        try:
            app.run(host='0.0.0.0', port=args.port, debug=args.debug_mode)
            print("Exiting normally.")
            break
        except socket.error as ex:
            # Old versions of the flaskd debug server would crash with a socket.error [32]: Broken Pipe
            # If the client connection died in the middle of a request.
            # This code auto-restarts the server, but it shouldn't be as important for newer versions of flask.
            traceback.print_exc()
            print("************************************")
            print("RESTARTING SERVER")
            print("************************************")
            time.sleep(5.0)
            continue
        except (SystemExit, KeyboardInterrupt) as ex:
            print("Log server killed via external signal: {}".format(ex.__class__.__name__))
            break
        except:
            traceback.print_exc()
            raise
        finally:
            close_all()
