from gemini_speech.certs import install as _install_certs
from gemini_speech.crashlog import install as _install_crashlog

_install_certs()
_install_crashlog()

from gemini_speech.__main__ import main

if __name__ == "__main__":
    main()
