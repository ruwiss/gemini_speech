from gemini_speech.crashlog import install as _install_crashlog

_install_crashlog()

import cookie_host  # noqa: F401
import server.speech_server  # noqa: F401
import gemini_speech.app  # noqa: F401
import gemini_speech.hosts  # noqa: F401
from gemini_speech.__main__ import main

if __name__ == "__main__":
    main()
