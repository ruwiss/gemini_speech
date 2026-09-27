def main():
    from .crashlog import install
    install()
    from .app import main as run_app
    run_app()


if __name__ == "__main__":
    main()
