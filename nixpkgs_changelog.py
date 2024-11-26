import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from subprocess import check_output

PKG_UPDATE_RE = re.compile(
    r"(?P<name>.+): "
    r"(?P<old_version>\d.+) -> (?P<new_version>\d[^, ]+)"
    r"(?P<comment>.*)"
)


@dataclass
class PkgUpdate:
    name: str
    old_version: str
    new_version: str
    comments: list[str]

    @staticmethod
    def parse_msg(msg):
        match = PKG_UPDATE_RE.match(msg)

        if match is None:
            return

        name, old_version, new_version, comment = match.groups()

        clean_comment = comment.strip(" ,")
        comments = [clean_comment] if clean_comment else []

        return PkgUpdate(name, old_version, new_version, comments)

    def merge(self, other: "PkgUpdate"):
        if other is None:
            return
        if self.name != other.name:
            return
        if self.new_version == other.old_version:
            return PkgUpdate(
                self.name,
                self.old_version,
                other.new_version,
                self.comments + other.comments,
            )
        if other.new_version == self.old_version:
            return PkgUpdate(
                self.name,
                other.old_version,
                self.new_version,
                self.comments + other.comments,
                )
        if self.new_version == other.new_version and self.old_version == other.old_version:
            return PkgUpdate(
                self.name,
                self.old_version,
                self.new_version,
                self.comments + other.comments,
                )

    def format_as_msg(self):
        update_msg = f"{self.name}: {self.old_version} -> {self.new_version}"
        if self.comments:
            return update_msg + ", " + ", ".join(self.comments)
        else:
            return update_msg


def version_diff_lines(old_versions, new_versions):
    lines = []
    for pkg_name in old_versions:
        old = old_versions.get(pkg_name, {}).get("version")
        new = new_versions.get(pkg_name, {}).get("version")

        if not old:
            lines.append(f"(old version missing for {pkg_name})")
            continue

        if not new:
            lines.append(f"(new version missing for {pkg_name})")
            continue

        if old != new:
            lines.append(f"{pkg_name}: {old} -> {new}")

    return lines


def get_interesting_commit_msgs(
        package_versions, nixpkgs_repo, old_rev, new_rev
):
    version_range = f"{old_rev}..{new_rev}"
    print(f"comparing {version_range}")
    lines = check_output(["git", "-C", str(nixpkgs_repo), "log", "--pretty=format:%s", version_range], text=True).splitlines()
    msgs = [l for l in lines if not l.startswith("Merge ")]
    search_words = set()
    for k, v in package_versions.items():
        search_words.add(k)
        search_words.add(v.get("pname"))

    return sorted({m for m in msgs if set(m.split(": ")) & search_words})


def filter_and_merge_commit_msgs(msgs):
    out_msgs = []
    parsed_updates: dict[str, list[PkgUpdate]] = defaultdict(list)
    ignored_msgs = [
        "github-runner: pass overridden version to build scripts",
        "gitlab: make Git package configurable",
        "gitlab: remove DB migration warning",
        "jicofo: 1.0-1050 -> 1.0-1059",
        "jitsi-meet: 1.0.7531 -> 1.0.7712",
        "jitsi-videobridge: 2.3-44-g8983b11f -> 2.3-59-g5c48e421",
        "jitsi-videobridge: 2.3-59-g5c48e421 -> 2.3-64-g719465d1",
        "libmodsecurity: 3.0.6 -> 3.0.7",
        "mongodb: fix build and sanitize package",
        "pystemd: fix runtime deps",
        "solr: 8.6.3 -> 8.11.1",
        "solr: 8.6.3 -> 8.11.2",
    ]

    for msg in sorted(msgs):
        if msg.startswith("linux") and "5.15" not in msg:
            continue

        if msg in ignored_msgs:
            continue

        if pkg_update := PkgUpdate.parse_msg(msg):
            merge_candidates = parsed_updates[pkg_update.name]
            if len(merge_candidates) > 0 and (merged := merge_candidates[-1].merge(pkg_update)):
                merge_candidates[-1] = merged
            else:
                merge_candidates.append(pkg_update)
        else:
            out_msgs.append(msg)

    out_msgs.extend(e.format_as_msg() for l in parsed_updates.values() for e in l)

    return sorted(out_msgs)


NIXPKGS_CHANGELOG_TEMPLATE = """\
< !--
Generated Nixpkgs Changelog. Adjust as necessary.

Output of version_diff:
{version_diff}
-->

## NixOS {nixos_version} platform
- Pull upstream NixOS changes, security fixes and package updates:
{nixpkgs_changelog}

"""


def generate_nixpkgs_changelog(
        nixpkgs_repo: Path,
        nixos_version: str,
        old_rev: str,
        new_rev: str,
        new_package_versions: dict,
        old_package_versions: dict,
):
    interesting_msgs = get_interesting_commit_msgs(
        new_package_versions, nixpkgs_repo, old_rev, new_rev
    )
    msgs = filter_and_merge_commit_msgs(interesting_msgs)
    version_diff = version_diff_lines(old_package_versions, new_package_versions)

    return NIXPKGS_CHANGELOG_TEMPLATE.format(version_diff="\n".join(version_diff),
                                             nixpkgs_changelog="\n".join("    - " + m for m in msgs),
                                             nixos_version=nixos_version)
