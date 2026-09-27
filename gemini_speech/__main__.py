def main():
    from .certs import install as install_certs
    from .crashlog import install as install_crashlog
    install_certs()
    install_crashlog()
    from .app import main as run_app
    run_app()


if __name__ == "__main__":
    main()
