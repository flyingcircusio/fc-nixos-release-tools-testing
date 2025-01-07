import subprocess

from .markdown import MarkdownTree
from .state import State
from .utils import (
    FC_NIXOS,
    checkout,
    ensure_repo,
    git,
    git_stdout,
    load_json,
    machine_prefix,
    rev_parse,
)

STEPS = [
    "prepare",
    "skip_no_change",
    "diff_release",
    "check_hydra",
    "collect_changelog",
    "merge",
    "backmerge",
    "add_detailed_changelog",
    "push",
]

CHANGELOG = FC_NIXOS / "changelog.d" / "CHANGELOG.md"


def generate_nixpkgs_changelog(old_rev: str, new_rev: str) -> MarkdownTree:
    res = MarkdownTree()
    res[
        "Detailed Changes"
    ] += f"- [platform code](https://github.com/flyingcircusio/fc-nixos/compare/{old_rev}...{new_rev})"
    versions_path = "release/versions.json"
    pversions_path = "release/package-versions.json"
    try:
        old_pversions = load_json(FC_NIXOS, old_rev, pversions_path)
        new_pversions = load_json(FC_NIXOS, new_rev, pversions_path)
        old_versions = load_json(FC_NIXOS, old_rev, versions_path)
        new_versions = load_json(FC_NIXOS, new_rev, versions_path)
        old_nixpkgs_rev = old_versions["nixpkgs"]["rev"]
        new_nixpkgs_rev = new_versions["nixpkgs"]["rev"]
    except subprocess.CalledProcessError:
        print(
            "Could not find relevant version file. Continuing without nixpkgs changelog..."
        )
        return res
    if old_nixpkgs_rev != new_nixpkgs_rev:
        lines = []
        for pkg_name in old_pversions:
            old = old_pversions.get(pkg_name, {}).get("version")
            new = new_pversions.get(pkg_name, {}).get("version")

            if not old and new:
                lines.append(f"{pkg_name}: (old version missing)")
            elif old and not new:
                lines.append(f"{pkg_name}: (new version missing)")
            elif old != new:
                lines.append(f"{pkg_name}: {old} -> {new}")

        res["NixOS XX.XX platform"] += (
            "- Pull upstream NixOS changes, security fixes and package updates:"
            + "".join("\n    - " + m for m in lines)
        )
        res[
            "Detailed Changes"
        ] += f"- [nixpkgs/upstream changes](https://github.com/flyingcircusio/nixpkgs/compare/{old_nixpkgs_rev}...{new_nixpkgs_rev})"
    return res


class Release:
    def __init__(self, state: State, nixos_version: str):
        self.release_id = state["release_id"]
        self.nixos_version = nixos_version
        self.branch_state = state["branches"][nixos_version]

        self.branch_dev = f"fc-{self.nixos_version}-dev"
        self.branch_stag = f"fc-{self.nixos_version}-staging"
        self.branch_prod = f"fc-{self.nixos_version}-production"

    def prepare(self):
        ensure_repo(FC_NIXOS, "git@github.com:flyingcircusio/fc-nixos.git")

        checkout(FC_NIXOS, self.branch_dev, reset=True, clean=True)
        checkout(FC_NIXOS, self.branch_stag, reset=True, clean=True)
        checkout(FC_NIXOS, self.branch_prod, reset=True, clean=True)

        self.branch_state["orig_staging_commit"] = rev_parse(
            FC_NIXOS, self.branch_stag
        )

    def skip_no_change(self):
        try:
            git(
                FC_NIXOS,
                "merge-base",
                "--is-ancestor",
                self.branch_stag,
                self.branch_prod,
            )
            print(f"No changes for {self.nixos_version} detected")
            raise SystemExit(1)
        except subprocess.CalledProcessError as e:
            if e.returncode != 1:
                raise

    def diff_release(self):
        def cherry(upstream: str, head: str):
            res = git_stdout(FC_NIXOS, "cherry", upstream, head, "-v")
            print(
                f"Commits in {head}, not in {upstream} ({len(res.splitlines())}):"
            )
            print()
            print(f"git cherry '{upstream}' '{head}' -v")
            print(res)
            print()

        dev_rev = rev_parse(FC_NIXOS, self.branch_dev)
        stag_rev = rev_parse(FC_NIXOS, self.branch_stag)
        prod_rev = rev_parse(FC_NIXOS, self.branch_prod)

        print(
            f"Comparing {self.branch_dev} to {self.branch_prod} {prod_rev}..{dev_rev}"
        )
        print(f"{self.branch_stag} is at {stag_rev}")

        print("")
        print("Merged PRs:")
        print()
        print(f"gh pr list --state=merged -B '{self.branch_dev}'")
        try:
            subprocess.run(
                ["gh", "pr", "list", "--state=merged", "-B", self.branch_dev],
                cwd=FC_NIXOS,
            )
        except FileNotFoundError:
            print("'gh' is not available. Please check merged PRs manually")
        print()

        cherry(self.branch_stag, self.branch_dev)
        cherry(self.branch_prod, self.branch_dev)

        print(f"git diff '{self.branch_prod}' '{self.branch_dev}'")
        print("Press Enter to show full diff")

        input()

        git(FC_NIXOS, "diff", self.branch_prod, self.branch_dev)

        print("Press enter to continue")
        input()

    def check_hydra(self):
        orig_stag_rev = self.branch_state.get(
            "orig_staging_commit", "<unknown rev>"
        )
        if self.nixos_version == "21.05":
            print(
                f"Staging: hydra commit id correct ({orig_stag_rev}), build green, does some physical machine in WHQ build it? [Enter to confirm]"
            )
            input()
            print(
                "Staging: sensu checks green for hardware in WHQ? [Enter to confirm]"
            )
            input()
            return
        prefix = machine_prefix(self.nixos_version)
        print(
            f"Staging: hydra commit id correct ({orig_stag_rev}), build green, does {prefix}stag00 build it? [Enter to confirm]"
        )
        input()
        print(
            f"Staging: releasetest sensu checks green? Look at https://sensu.rzob.gocept.net/#/clients?q={prefix}* [Enter to confirm]"
        )
        input()

    def collect_changelog(self):
        checkout(FC_NIXOS, self.branch_stag)
        if not CHANGELOG.parent.exists():
            print(
                f"Could not find '{str(CHANGELOG.parent)}'. Skipping changelog generation..."
            )
            return

        new_fragment = MarkdownTree.collect(
            filter(CHANGELOG.__ne__, CHANGELOG.parent.rglob("*.md")), FC_NIXOS
        )
        new_fragment.strip()

        self.branch_state["changelog"] = new_fragment.to_str()

        new_fragment.add_header(f"Release {self.release_id}")
        new_changelog = new_fragment.to_str()
        if CHANGELOG.exists():
            new_changelog += "\n" + CHANGELOG.read_text()
        CHANGELOG.write_text(new_changelog)

        try:
            git(FC_NIXOS, "add", str(CHANGELOG.relative_to(FC_NIXOS)))
            git(FC_NIXOS, "commit", "-m", "Collect changelog fragments")
        except subprocess.CalledProcessError:
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
        self.branch_state["new_production_commit"] = rev_parse(
            FC_NIXOS, self.branch_prod
        )

    def backmerge(self):
        checkout(FC_NIXOS, self.branch_dev)
        msg = f"Backmerge branch '{self.branch_prod}' into '{self.branch_dev}'' for release {self.release_id}"
        git(FC_NIXOS, "merge", "-m", msg, self.branch_prod)

    def add_detailed_changelog(self):
        old_rev = rev_parse(FC_NIXOS, "origin/" + self.branch_prod)
        new_rev = rev_parse(FC_NIXOS, self.branch_prod)

        new_fragment = MarkdownTree.from_str(
            self.branch_state.get("changelog", "")
        )
        new_fragment |= generate_nixpkgs_changelog(old_rev, new_rev)

        print("Press enter to edit the generated changelog fragment")
        input()
        new_fragment.open_in_editor()
        self.branch_state["changelog"] = new_fragment.to_str()

    def push(self):
        print(f"Committed changes ({self.nixos_version}):")
        print("fc-nixos:")
        git(FC_NIXOS, "log", "--graph", "--decorate", "--format=short", "-n3")
        print()
        print(
            "If this looks correct, press Enter to push (or use ^C to abort)."
        )
        input()
        git(
            FC_NIXOS,
            "push",
            "origin",
            self.branch_dev,
            self.branch_stag,
            self.branch_prod,
        )


def main(state: State, nixos_version: str, steps: list[str]):
    if nixos_version in state["branches"]:
        print(f"Branch '{nixos_version}' already added")
        return
    release = Release(state, nixos_version)
    print(f"Adding {nixos_version} to {state['release_id']}")
    for step_name in steps:
        print(f"\nRelease step: {step_name}")
        getattr(release, step_name)()
