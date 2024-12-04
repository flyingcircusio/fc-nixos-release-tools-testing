"""
This script should be run when an automatic update-nixpkgs PR has been merged.
It will merge the corresponding flyingcircus/nixpkgs PR and cleanup
all old fc-nixos and nixpkgs PRs/branches that haven't been merged.
"""

import datetime
import os
from dataclasses import dataclass
from logging import info, warning

from git import GitCommandError, Repo
from github import Auth, Github

from update_nixpkgs import FC_NIXOS_REPO, NIXPKGS_REPO


@dataclass
class Remote:
    url: str
    branches: list[str]


def nixpkgs_repository(directory: str, remotes: dict[str, Remote]) -> Repo:
    info("Updating nixpkgs repository.")
    if os.path.exists(directory):
        repo = Repo(directory)
    else:
        repo = Repo.init(directory, mkdir=True)

    for name, remote in remotes.items():
        info(f"Updating nixpkgs repository remote `{name}`.")
        if name in repo.remotes and repo.remotes[name].url != remote.url:
            repo.delete_remote(repo.remote(name))
        if name not in repo.remotes:
            repo.create_remote(name, remote.url)

        for branch in remote.branches:
            info(
                f"Fetching nixpkgs repository remote `{name}` - branch `{branch}`."
            )
            getattr(repo.remotes, name).fetch(
                refspec=branch, filter="blob:none"
            )

    return repo


def rebase_nixpkgs(
    gh: Github, nixpkgs_repo: Repo, target_branch: str, integration_branch: str
) -> bool:
    """Rebase nixpkgs repo integration branch onto target branch
    Returns: True when successful, False when unsuccessful.
    """
    info("Rebase nixpkgs repo integration branch onto target branch.")
    if nixpkgs_repo.is_dirty():
        raise Exception("Repository is dirty!")

    nixpkgs_repo.git.checkout(target_branch)

    try:
        nixpkgs_repo.git.rebase(f"origin/{integration_branch}")
    except GitCommandError as e:
        warning(f"Rebase failed:\n{e.stderr}")
        nixpkgs_repo.git.rebase(abort=True)
        warning("Aborted rebase.")
        return False

    nixpkgs_repo.git.push(force_with_lease=True)
    # Tag result so that the commit is always referenced so that other release tooling can find it.
    nixpkgs_repo.git.tag(integration_branch, message=integration_branch)
    nixpkgs_repo.git.push("origin", tags=True)
    gh.get_repo(NIXPKGS_REPO).get_git_ref(
        f"heads/{integration_branch}"
    ).delete()
    return True


def cleanup_old_prs_and_branches(gh: Github, merged_integration_branch: str):
    info("Cleaning up old PRs and branches.")
    fc_nixos_repo = gh.get_repo(FC_NIXOS_REPO)
    nixpkgs_repo = gh.get_repo(NIXPKGS_REPO)
    merged_integration_branch_date = datetime.date.fromisoformat(
        merged_integration_branch.split("/")[2]
    )
    # branches will be closed automatically by GitHub, when the branch is deleted
    for repo in [fc_nixos_repo, nixpkgs_repo]:
        for branch in repo.get_branches():
            if not branch.name.startswith("nixpkgs-auto-update/"):
                continue
            branch_datestr = branch.name.split("/")[2]
            if (
                datetime.date.fromisoformat(branch_datestr)
                < merged_integration_branch_date
            ):
                repo.get_git_ref(f"heads/{branch.name}").delete()


def run(
    merged_pr_id: str,
    nixpkgs_origin_url: str,
    nixpkgs_dir: str,
    github_access_token: str,
):
    gh = Github(auth=Auth.Token(github_access_token))
    fc_nixos_pr = gh.get_repo(FC_NIXOS_REPO).get_pull(int(merged_pr_id))
    pr_platform_version = fc_nixos_pr.base.ref.split("-")[1]
    integration_branch = fc_nixos_pr.head.ref
    nixpkgs_target_branch = f"nixos-{pr_platform_version}"

    remotes = {
        "origin": Remote(
            nixpkgs_origin_url,
            [integration_branch, nixpkgs_target_branch],
        )
    }
    nixpkgs_repo = nixpkgs_repository(nixpkgs_dir, remotes)
    if rebase_nixpkgs(
        gh,
        nixpkgs_repo,
        nixpkgs_target_branch,
        integration_branch,
    ):
        fc_nixos_pr.create_issue_comment(
            f"Rebased nixpkgs `{nixpkgs_target_branch}` branch successfully."
        )
        cleanup_old_prs_and_branches(gh, integration_branch)
