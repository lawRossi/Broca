import argparse
import os
import sys


def init_project(args):
    project_name = args.project_name
    project_type = args.project_type
    if os.path.exists(project_name):
        raise RuntimeError(f"directory {project_name} already exists")
    os.makedirs(project_name)
    platform = sys.platform

    if project_type == "simple":
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        template_dir = os.path.join(base_dir, "resource\\templates\\simple")
        if platform == "win32":
            cmd = f"xcopy {template_dir}\\*.* {project_name} /s"
            os.system(cmd)
        elif platform == "linux":
            cmd = f"cp {template_dir}\\* {project_name}"
            os.system(cmd)
    print(f"project {project_name} created")


def add_init_project_parser(parent_parsers, subparsers):
    init_parser = subparsers.add_parser(
        "init",
        parents=parent_parsers,
        conflict_handler="resolve",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        help="Initialize a Broca project",
    )
    init_parser.set_defaults(func=init_project)
    init_parser.add_argument("--project_name",
                        type=str,
                        required=True,
                        help="The name of the project")

    init_parser.add_argument("--project_type",
                        default="simple",
                        type=str,
                        required=False,
                        help="The type of project to initialize")


def init_agent(args):
    agent_name = args.agent_name
    if os.path.exists(agent_name):
        raise RuntimeError(f"directory {agent_name} already exists")
    os.makedirs(agent_name)
    platform = sys.platform
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    template_dir = os.path.join(base_dir, "resource\\templates\\simple\\agent")
    if platform == "win32":
        cmd = f"xcopy {template_dir}\\*.* {agent_name} /s"
        os.system(cmd)
    elif platform == "linux":
        cmd = f"cp {template_dir}\\* {agent_name}"
        os.system(cmd)
    print(f"agent {agent_name} created")


def add_init_agent_parser(parent_parsers, subparsers):
    init_parser = subparsers.add_parser(
        "init_agent",
        parents=parent_parsers,
        conflict_handler="resolve",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        help="Initialize a Broca project",
    )
    init_parser.set_defaults(func=init_agent)
    init_parser.add_argument("--agent_name",
                        type=str,
                        required=True,
                        help="The name of the agent")


def create_argument_parser() -> argparse.ArgumentParser:
    """Parse all the command line arguments for the training script."""

    parser = argparse.ArgumentParser(
        prog="broca",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Broca command line interface.",
    )

    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parsers = [parent_parser]

    subparsers = parser.add_subparsers(help="Broca commands")
    add_init_project_parser(parent_parsers, subparsers)
    add_init_agent_parser(parent_parsers, subparsers)
    return parser
