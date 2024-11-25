#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
from pathlib import Path
from subprocess import CalledProcessError, run

DEFAULT_NIXOS_VERSIONS = ["21.05", "23.05", "23.11", "24.05"]
STEPS = ["prepare", "skip_no_change", "collect_changelog", "merge", "backmerge", "add_detailed_changelog", "push"]

WORK_DIR = Path("work")
FC_NIXOS = WORK_DIR / "fc-nixos"
FC_DOCS = WORK_DIR / "doc"
CHANGELOG = FC_NIXOS / "changelog.d" / "CHANGELOG.md"
TEMP_CHANGELOG = CHANGELOG.with_suffix(CHANGELOG.suffix + ".tmp")

SKIP_BRANCH = object()


def release_id_type(arg_value):
    if not re.compile("^[0-9]{4}_[0-9]{3}$").match(arg_value):
        raise argparse.ArgumentTypeError(
            "invalid release id format. Expected: YYYY_NNN"
        )
    return arg_value


def git(path: Path, *cmd: str, check=True, **kw):
    return run(["git", "-C", str(path)] + list(cmd), check=check, **kw)


def git_stdout(*args, **kw):
    return git(*args, **kw, check=True, text=True, stdout=subprocess.PIPE).stdout


def git_remote(path: Path):
    out = git_stdout(path, "remote", "-v")
    return re.findall(r"^origin\s(.+?)\s\(.+\)$", out, re.MULTILINE)


def ensure_repo(path: Path, url: str):
    if not path.exists():
        path.parent.mkdir(exist_ok=True)
        run(["git", "clone", url, str(path)], check=True)
    if (remotes := set(git_remote(path))) != {url}:
        print(f"Remote 'origin' of {path} did not match the expected value of '{url}'. Found '{remotes}'")
        print(f"Remove '{path}' to start from scratch or skip this stage.")
        exit(2)
    git(path, "fetch", "origin", "--tags", "--prune", "--prune-tags", "--force")


def checkout(path: Path, branch: str, reset: bool = False, clean: bool = False):
    git(path, "checkout", "-q", branch)
    if reset:
        git(path, "reset", "-q", "--hard", f"origin/{branch}")
        # git(path, "merge", "--ff-only")  # expected to fail on unclean/unpushed workdirs
    if clean:
        git(path, "clean", "-d", "--force")


class Release:
    def __init__(self, release_id: str, nixos_version: str):
        self.release_id = release_id
        self.nixos_version = nixos_version

        self.branch_dev = f"fc-{self.nixos_version}-dev"
        self.branch_stag = f"fc-{self.nixos_version}-staging"
        self.branch_prod = f"fc-{self.nixos_version}-production"
        self.branch_doc = "master"

    @property
    def doc_fragment_path(self):
        return FC_DOCS / "changelog.d" / f"{self.nixos_version}.md"

    @property
    def doc_fragment_detailed_path(self):
        return self.doc_fragment_path.with_name(f"{self.nixos_version}_detailed.md")

    def prepare(self):
        ensure_repo(FC_DOCS, "git@github.com:flyingcircusio/doc.git")
        ensure_repo(FC_NIXOS, "git@github.com:flyingcircusio/fc-nixos.git")

        checkout(FC_NIXOS, self.branch_dev, reset=True, clean=True)
        checkout(FC_NIXOS, self.branch_stag, reset=True, clean=True)
        checkout(FC_NIXOS, self.branch_prod, reset=True, clean=True)
        checkout(FC_DOCS, self.branch_doc, reset=True, clean=True)

    def skip_no_change(self):
        try:
            git(FC_NIXOS, "merge-base", "--is-ancestor", self.branch_stag, self.branch_prod)
        except CalledProcessError as e:
            if e.returncode != 1:
                raise

        print(f"No changes for {self.nixos_version} detected")
        return SKIP_BRANCH

    def collect_changelog(self):
        checkout(FC_NIXOS, self.branch_stag)
        if not CHANGELOG.parent.exists():
            print(f"Could not find '{str(CHANGELOG.parent)}'. Skipping changelog generation...")
            # TODO: offer manual edit?
            return
        if self.doc_fragment_path.exists():
            print(f"The changelog fragment '{self.doc_fragment_path}' already exists")
            print("Remove it (commit & push) or skip changelog generation")
            raise RuntimeError()

        TEMP_CHANGELOG.open("w").close()  # truncate
        try:
            run(["scriv", "collect", "--add"], check=True)
        except CalledProcessError:
            TEMP_CHANGELOG.unlink()
            print(
                "Failed to collect Changelog. Continuing without changelog..."
            )
            return

        new_fragment = TEMP_CHANGELOG.read_text()
        # TODO: remove empty sections

        doc_fragment = new_fragment.replace(
            "\n## Impact", f"\n## Impact\n### {self.nixos_version}"
        )
        doc_fragment = doc_fragment.replace(
            "\n## NixOS XX.XX platform",
            f"\n## NixOS {self.nixos_version} platform",
        )
        self.doc_fragment_path.write_text(doc_fragment)

        new_changelog = f"# Release {self.release_id}\n\n" + new_fragment
        if CHANGELOG.exists():
            new_changelog += "\n" + CHANGELOG.read_text()
        CHANGELOG.write_text(new_changelog)

        TEMP_CHANGELOG.unlink()

        git(FC_DOCS, "add", str(self.doc_fragment_path.relative_to(FC_DOCS)))
        git(FC_DOCS, "commit", "-m", f"Add fragment for {self.nixos_version}")
        try:
            git(FC_NIXOS, "add", str(TEMP_CHANGELOG.relative_to(FC_NIXOS)), str(CHANGELOG.relative_to(FC_NIXOS)))
            git(FC_NIXOS, "commit", "-m", "Collect changelog fragments")
        except CalledProcessError:
            print(
                "Failed to commit Changelog. Commit it manually and continue after the `collect_changelog` stage"
            )
            raise

    def merge(self):
        checkout(FC_NIXOS, self.branch_prod)
        msg = (
            f"Merge branch '{self.branch_stag}' into "
            f"'{self.branch_prod}' for release {self.release_id}"
        )
        git(FC_NIXOS, "merge", "-m", msg, self.branch_stag)

    def backmerge(self):
        checkout(FC_NIXOS, self.branch_dev)
        msg = f"Backmerge branch '{self.branch_prod}' into '{self.branch_dev}'' for release {self.release_id}"
        git(FC_NIXOS, "merge", "-m", msg, self.branch_prod)

    def add_detailed_changelog(self):
        versions_json_path = "release/versions.json"
        old_hash = git_stdout(FC_NIXOS, "rev-parse", "--verify", "origin/" + self.branch_prod).strip()
        new_hash = git_stdout(FC_NIXOS, "rev-parse", "--verify", self.branch_prod).strip()
        detailed_changes = "## Detailed Changes\n"
        detailed_changes += f"- NixOS {self.nixos_version}: [platform code](https://github.com/flyingcircusio/fc-nixos/compare/{old_hash}...{new_hash})"
        try:
            old_versions = git_stdout(FC_NIXOS, "show", "origin/" + self.branch_prod + ":" + versions_json_path)
            new_versions = git_stdout(FC_NIXOS, "show", self.branch_prod + ":" + versions_json_path)
            old_nixpkgs_hash = json.loads(old_versions)["nixpkgs"]["rev"]
            new_nixpkgs_hash = json.loads(new_versions)["nixpkgs"]["rev"]
            if old_nixpkgs_hash != new_nixpkgs_hash:
                detailed_changes += f", [nixpkgs/upstream changes](https://github.com/flyingcircusio/nixpkgs/compare/{old_nixpkgs_hash}...{new_nixpkgs_hash})"
        except CalledProcessError:
            print(f"Could not find '{versions_json_path}'. Continuing without nixpkgs changelog...")
        print(detailed_changes)
        self.doc_fragment_detailed_path.write_text(detailed_changes)
        git(FC_DOCS, "add", str(self.doc_fragment_detailed_path.relative_to(FC_DOCS)))
        git(FC_DOCS, "commit", "-m", f"Add detailed fragment for {self.nixos_version}")

    def push(self):
        print(f"Committed changes ({self.nixos_version}):")
        print("fc-nixos:")
        git(FC_NIXOS,
            "log", "--graph", "--decorate", "--format=short", "-n3",
            env={"PAGER": ""},
            )
        print("doc:")
        git(FC_DOCS,
            "log", "--graph", "--decorate", "--format=short", f"origin/{self.branch_doc}..{self.branch_doc}",
            env={"PAGER": ""},
            )
        cmd = f"git -C {FC_NIXOS} push origin {self.branch_dev} {self.branch_stag} {self.branch_prod} && git -C {FC_DOCS} push origin {self.branch_doc}"
        # cmd = f"git -C {FC_NIXOS} push --dry-run origin {self.branch_dev} {self.branch_stag} {self.branch_prod} && git -C {FC_DOCS} push --dry-run origin {self.branch_doc}"
        print(
            "If this looks correct, press Enter to push (or use ^C to abort all releases and ^D to abort this release)."
        )
        print(f"This will issue: `{cmd}`")
        try:
            input()
        except EOFError:
            return SKIP_BRANCH
        run(cmd, shell=True, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("release_id", type=release_id_type)
    parser.add_argument(
        "--nixos_versions", default=DEFAULT_NIXOS_VERSIONS, nargs="*", help="(default: %(default)s)"
    )
    parser.add_argument(
        "--steps", choices=["all"] + STEPS, default="all", nargs="*", help="(default: %(default)s)"
    )
    args = parser.parse_args()
    if args.steps == "all" or "all" in args.steps:
        args.steps = STEPS

    for nixos_version in args.nixos_versions:
        release = Release(args.release_id, nixos_version)
        print(f"Performing release for {nixos_version} ({args.release_id})")
        for step_name in args.steps:
            print(f"Release step: {step_name}")
            rc = getattr(release, step_name)()
            if rc == SKIP_BRANCH:
                print(f"Aborted release for {nixos_version}")
                break


if __name__ == "__main__":
    main()
