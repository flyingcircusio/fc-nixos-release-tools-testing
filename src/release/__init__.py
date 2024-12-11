import argparse
import os
import re
import subprocess
from functools import partial

import requests

from . import add_branch, doc
from .state import STAGE, State, load_state, new_state, store_state
from .utils import (
    EDITOR,
    FC_DOCS,
    FC_NIXOS,
    checkout,
    ensure_repo,
    git,
    machine_prefix,
)

AVAILABLE_CMDS = {
    STAGE.INIT: ["init", "status"],
    STAGE.BRANCH: ["add-branch", "test-branch", "doc", "status"],
    STAGE.TAG: ["tag", "status"],
    STAGE.DONE: ["init", "status"],
}


def release_id_type(arg_value):
    if not re.compile("^[0-9]{4}_[0-9]{3}$").match(arg_value):
        raise argparse.ArgumentTypeError(
            "invalid release id format. Expected: YYYY_NNN"
        )
    return arg_value


def release_date_type(arg_value):
    if not re.match(r"\d{4}-\d{2}-\d{2}$", arg_value):
        raise argparse.ArgumentTypeError(
            "Release date must be formatted as YYYY-MM-DD"
        )
    return arg_value


def comma_separated_list(arg_value: str, choices=None):
    separated = arg_value.split(",")
    for e in separated:
        if choices and e not in choices:
            raise argparse.ArgumentTypeError(
                f"invalid element '{e}'. Must be one of '{','.join(choices)}'"
            )
    return separated


def init(state: State, release_id: str, release_date: str):
    state.clear()
    state.update(new_state())
    state["release_id"] = release_id
    state["release_date"] = release_date
    state["stage"] = STAGE.BRANCH
    # TODO check if release_id already exists/suggest new one


def test_branch(state: State, nixos_version: str):
    if nixos_version not in state["branches"]:
        print(f"Please add '{nixos_version}' before testing it")
        return
    branch_state = state["branches"][nixos_version]
    if "tested" in branch_state:
        print(f"'{nixos_version}' already tested")
        return

    ensure_repo(FC_DOCS, "git@github.com:flyingcircusio/doc.git")
    checkout(FC_DOCS, "master", reset=True, clean=True)

    prod_commit = branch_state.get("new_production_commit", "<unknown rev>")
    print(f"Production: hydra commit id correct? ({prod_commit}), build green?")
    while not (hydra_id := input("Hydra eval ID: ")).isdigit():
        pass
    branch_state["hydra_eval_id"] = hydra_id
    print(
        f"Production: directory: create release '{state['release_id']}' for {nixos_version}-production using hydra eval ID {hydra_id}, valid from {state['release_date']} 21:00"
    )
    print(
        "(releasetest VMs will already use this as the *next* release) [Enter to confirm]"
    )
    input()

    try:
        r = requests.get(
            f"https://my.flyingcircus.io/releases/metadata/fc-{nixos_version}-production/{state['release_id']}",
            timeout=5,
        )
        r.raise_for_status()
        channel_url = r.json()["channel_url"]
        frag_path = FC_DOCS / "changelog.d" / f"{nixos_version}_channel_url.md"
        frag_path.write_text(
            f"## NixOS {nixos_version} platform\n- Production channel for this release: {channel_url}"
        )
        git(FC_DOCS, "add", frag_path.relative_to(FC_DOCS))
        print("Added channel url fragment")
    except (requests.RequestException, KeyError):
        print(
            "Failed to retrieve channel url. Please add it manually in the next step"
        )
    if nixos_version == "21.05":
        print(
            "Production: switch a test VM to the 21.05-production-next channel. Is it working correctly?"
        )
    else:
        prefix = machine_prefix(nixos_version)
        print(
            f"Production: On {prefix}prod00, switch to new system. Is it working correctly?"
        )
    print(
        "Check switch output for unexpected service restarts, compare with changelog, impact properly documented? [Enter to edit]"
    )
    print(
        "(This opens the main fragment. Changes from the nixpkgs fragment will not be visible)"
    )  # TODO
    input()
    main_changelog_fragment = FC_DOCS / "changelog.d" / f"{nixos_version}.md"
    subprocess.run([EDITOR, str(main_changelog_fragment)])
    git(FC_DOCS, "add", str(main_changelog_fragment.relative_to(FC_DOCS)))
    git(
        FC_DOCS,
        "commit",
        "--allow-empty",
        "-m",
        f"Update fragment for {nixos_version}",
    )

    input("Press enter to push update")
    git(FC_DOCS, "push", "origin", "master")

    branch_state["tested"] = True


def tag(state: State):
    ensure_repo(FC_NIXOS, "git@github.com:flyingcircusio/fc-nixos.git")
    print(
        "activate 'keep' for the Hydra job flyingcircus:fc-*-production:release [Enter]"
    )
    input()
    for nixos_version in state["branches"].keys():
        git(
            FC_NIXOS,
            "tag",
            f"fc/r{state['release_id']}/{nixos_version}",
            f"fc-{nixos_version}-production",
        )

    git(FC_NIXOS, "push", "--tags")
    state["stage"] = STAGE.DONE


def status(state: State, header: bool = True):
    if header:
        if "release_id" in state and "release_date" in state:
            print(
                f"Current release: {state['release_id']} ({state['release_date']})"
            )
        print(f"You are in stage: {state['stage']}")
        print(
            "The following subcommands are available: "
            + ", ".join(AVAILABLE_CMDS[state["stage"]])
        )
        print()

        print("This release contains the following nixos versions:")
        for k, v in state["branches"].items():
            test_state = "tested" if "tested" in v else "untested"
            print(f"{k}: {test_state}")
        print()
    match state["stage"]:
        case STAGE.INIT:
            print("Call init to create a new release")
        case STAGE.BRANCH:
            print("Call add-branch to add a new nixos version to this release")
            print("Call test-branch to test an existing nixos version")
            print("Call doc to finish")
        case STAGE.TAG:
            print("Remember to do the following tasks:")
            print("Now:")
            print("check rendered changelog")
            print("statuspage: create maintenance (only notifications now)")
            print(
                f"Announce release in Matrix (room General) and link to change log ({state['changelog_url']})"
            )
            print()
            print(
                f"Shortly Before Release ({state['release_date']} 20:45 Europe/Berlin)"
            )
            print(
                "double-check that production environments are set up correctly:"
            )
            for k, v in state["branches"].items():
                print(
                    f"release '{state['release_id']}' for {k}-production using hydra eval ID {v['hydra_eval_id']} (commit {v['new_production_commit']}), valid from {state['release_date']} 21:00"
                )
            print()
            print(
                f"Around the announced release time ({state['release_date']} 21:00 Europe/Berlin) (shortly before or after):"
            )
            print("Call tag")
        case STAGE.DONE:
            print("Summary of this release:")
            print(f"Release at: {state['release_date']} 21:00")
            print("Release ID: " + state["release_id"])
            print("Changelog url: " + state["changelog_url"])
            for k, v in state["branches"].items():
                print()
                print(f"## NixOS {k}")
                print("New production commit: " + v["new_production_commit"])
                print("Old staging commit: " + v["orig_staging_commit"])
                print("Hydra eval id: " + v["hydra_eval_id"])

            print()
            print("Call init to create a new release")


def main():
    os.environ["PAGER"] = ""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    subparser = parser.add_subparsers(dest="command")

    init_parser = subparser.add_parser("init")
    init_parser.add_argument(
        "release_id",
        type=release_id_type,
        help="Release id in the form YYYY_NNN",
    )
    # default_release_date = datetime.date.today() + datetime.timedelta(days=1)
    init_parser.add_argument(
        "release_date",
        # nargs="?",
        # default=default_release_date.strftime("%Y-%m-%d"),
        type=release_date_type,
        help="set planned roll-out date",
    )
    init_parser.set_defaults(func=init)

    status_parser = subparser.add_parser("status")
    status_parser.set_defaults(func=status)

    add_branch_parser = subparser.add_parser("add-branch")
    add_branch_parser.add_argument(
        "nixos_version",
        help="NixOS versions to add.",
    )
    add_branch_parser.add_argument(
        "--steps",
        default=",".join(add_branch.STEPS),
        nargs="?",
        type=partial(comma_separated_list, choices=add_branch.STEPS),
        help="Comma-separated list of steps to execute.",
    )
    add_branch_parser.set_defaults(func=add_branch.main)

    test_branch_parser = subparser.add_parser("test-branch")
    test_branch_parser.add_argument(
        "nixos_version",
        help="NixOS versions to test.",
    )
    test_branch_parser.set_defaults(func=test_branch)

    doc_parser = subparser.add_parser("doc")
    doc_parser.set_defaults(func=doc.main)

    tag_parser = subparser.add_parser("tag")
    tag_parser.set_defaults(func=tag)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_usage()
        return

    state = load_state()

    if args.command not in AVAILABLE_CMDS[state["stage"]]:
        print(f"{args.command} is not available in stage '{state['stage']}'")
        print()
        status(state)
        return

    func = args.func
    kwargs = dict(args._get_kwargs())
    del kwargs["func"]
    del kwargs["command"]
    func(state, **kwargs)
    if func != status:
        print()
        status(state, header=False)

    store_state(state)


if __name__ == "__main__":
    main()
