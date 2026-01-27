import os
import shutil
from client import CLIENT_LOG_DIR, run_client
from server import SERVER_LOG_DIR, run_server
import threading


def test():
    shutil.rmtree(CLIENT_LOG_DIR, ignore_errors=True)
    shutil.rmtree(SERVER_LOG_DIR, ignore_errors=True)

    server_thread = threading.Thread(target=run_server)
    client_thread = threading.Thread(target=run_client)

    server_thread.start()
    client_thread.start()

    server_thread.join()
    client_thread.join()

    server_thread = None
    client_thread = None


if __name__ == "__main__":
    test()
