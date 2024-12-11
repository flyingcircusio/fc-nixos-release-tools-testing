import subprocess

from .state import STAGE, State
from .utils import EDITOR, FC_DOCS, checkout, ensure_repo, git

INDEX_TEMPLATE = """\
# {year}

Releases performed in {year}.

```{{toctree}}
:maxdepth: 1

{releases}
```
"""

CHANGELOG_TEMPLATE = """\
---
Publish Date: '{release_date}'
---

# Release {release_id} ({release_date})

% scriv-insert-here

## Documentation

- nothing yet

% vim: set spell spelllang=en:
"""


def main(state: State):
    for k, v in state["branches"].items():
        if "tested" not in v:
            print(f"'{k}' is not tested")
            return
    branches = state["branches"].keys()
    print(
        "This will release the changelog for the following versions: "
        + ", ".join(branches)
    )
    ensure_repo(FC_DOCS, "git@github.com:flyingcircusio/doc.git")
    checkout(FC_DOCS, "master", reset=True, clean=True)

    print("Review open/merged PRs:")
    try:
        subprocess.run(
            ["gh", "pr", "list", "--state=all", "-B", "master"],
            cwd=FC_DOCS,
        )
    except FileNotFoundError:
        print("'gh' is not available. Please check PRs manually")
    input("Press enter to continue")

    year, release_num = state["release_id"].split("_", maxsplit=1)
    new_file = FC_DOCS.joinpath(f"src/changes/{year}/r{release_num}.md")

    new_text = CHANGELOG_TEMPLATE.format(
        release_id=state["release_id"], release_date=state["release_date"]
    )
    new_file.write_text(new_text)
    new_file_symlink = FC_DOCS.joinpath("CHANGES.md")
    new_file_symlink.unlink(missing_ok=True)
    new_file_symlink.symlink_to(new_file.relative_to(new_file_symlink.parent))

    subprocess.check_call(["scriv", "collect"], cwd=FC_DOCS)

    index_file = FC_DOCS / f"src/changes/{year}/index.md"
    releases = [
        e.name.removesuffix(".md")
        for e in FC_DOCS.glob(f"src/changes/{year}/r*.md")
        if e.is_file()
    ]
    index_content = INDEX_TEMPLATE.format(
        year=year, releases="\n".join(sorted(releases))
    )
    index_file.write_text(index_content)

    input("Press enter to open the new changelog (remove empty sections)")
    subprocess.run([EDITOR, str(new_file)])
    print("Committing changes")
    git(
        FC_DOCS,
        "add",
        str(new_file.relative_to(FC_DOCS)),
        str(index_file.relative_to(FC_DOCS)),
        str(new_file_symlink.relative_to(FC_DOCS)),
    )
    git(FC_DOCS, "commit", "-m", f"add changelog r{release_num}")

    input("Press enter to push")
    git(FC_DOCS, "push", "origin", "master")

    state["changelog_url"] = (
        f"https://doc.flyingcircus.io/platform/changes/{year}/{release_num}.html"
    )
    state["stage"] = STAGE.TAG
