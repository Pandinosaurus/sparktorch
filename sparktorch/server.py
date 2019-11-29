"""
The MIT License

Copyright 2019 Derek Miller

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions
of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

import socket
from multiprocessing import Process
from flask import Flask, request
import dill
from sparktorch.util import load_torch_model, TorchObj
from sparktorch.rw_lock import RWLock

import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)


class Server(object):

    def __init__(
        self,
        torch_obj: TorchObj,
        master_url: str = None,
        port: int = 3000,
        acquire_lock: bool = False
    ):
        self.torch_obj = load_torch_model(torch_obj)

        self.model = self.torch_obj.model

        self.state_dict = self.model.state_dict()
        self.criterion = self.torch_obj.criterion
        self.optimizer = self.torch_obj.optimizer

        self.master_url = master_url
        self.port = port
        self.error_count = 0
        self.acquire_lock = acquire_lock

        self.server = Process(target=self.start_service)

    @staticmethod
    def determine_master(port: int):
        try:
            master_url = socket.gethostbyname(socket.gethostname()) + ':' + str(port)
            return master_url
        except:
            return 'localhost:' + str(port)

    def start_server(self):
        self.server.start()
        self.master_url = Server.determine_master(self.port)

    def stop_server(self):
        self.server.terminate()
        self.server.join()

    def start_service(self):
        app = Flask(__name__)
        self.app = app
        self.model.train()
        lock = RWLock()
        lock_acquired = self.acquire_lock

        @app.route('/')
        def home():
            return 'sparktorch'

        @app.route('/parameters', methods=['GET'])
        def get_parameters():
            if lock_acquired:
                lock.acquire_read()
            state = dill.dumps(self.state_dict)
            if lock_acquired:
                lock.release()
            return state

        @app.route('/update', methods=['POST'])
        def update_parameters():

            if lock_acquired:
                lock.acquire_write()

            try:
                gradients = dill.loads(request.data)

                for index, param in enumerate(self.model.parameters()):
                    param.grad = gradients[index]

                self.optimizer.step()

                self.state_dict = self.model.state_dict()

            except Exception as e:
                self.error_count += 1
                if self.error_count > 10:
                    raise RuntimeError(f"Max Errors {str(e)}")
            finally:
                if lock_acquired:
                    lock.release()

            return 'completed'

        self.app.run(host='0.0.0.0', use_reloader=False, threaded=True, port=self.port)


