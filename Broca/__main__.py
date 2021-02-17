from Broca.cli.run import create_argument_parser


def main():
    parser = create_argument_parser()
    cmdline_arguments = parser.parse_args()
    if hasattr(cmdline_arguments, "func"):
        cmdline_arguments.func(cmdline_arguments)
    else:
        parser.print_help()
        exit(1)


if __name__ == "__main__":
    main()
