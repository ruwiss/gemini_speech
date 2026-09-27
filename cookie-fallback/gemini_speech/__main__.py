import os
import sys


def _root_on_path():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)


def main():
    from .crashlog import install
    install()
    if "--server" in sys.argv:
        _root_on_path()
        from server.speech_server import serve
        serve()
        return
    if "--cookie-host" in sys.argv:
        _root_on_path()
        from cookie_host import run
        run()
        return
    if "--install-host" in sys.argv:
        from .hosts import install
        install()
        return
    if "--self-test-mic" in sys.argv:
        from .crashlog import note
        from .app import _qt_log
        from PyQt6.QtCore import qInstallMessageHandler
        from PyQt6.QtWidgets import QApplication
        qInstallMessageHandler(_qt_log)
        app = QApplication([])
        from .audio import Recorder
        from .indicator import Indicator
        note("self-test mic")
        recorder = Recorder()
        recorder.start()
        note("mic open")
        indicator = Indicator()
        indicator.show_recording()
        note("indicator shown")
        import time
        time.sleep(0.5)
        pcm = recorder.stop()
        indicator.dismiss()
        note("self-test ok bytes %s" % len(pcm))
        app.processEvents()
        return
    from .app import main as run_app
    run_app()


if __name__ == "__main__":
    main()
