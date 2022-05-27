import random
import string

import jmespath
from loguru import logger
from requests import put

from .http_requests import get_request, patch_request, post_request


class GitHubAPI:
    """Interact with the GitHub API and perform varios git-flow tasks"""

    def __init__(self, inputs):
        self.inputs = inputs
        self.api_url = "/".join(
            ["https://api.github.com", "repos", self.inputs.repository]
        )

    def _assign_labels(self, pr_url):
        """Assign labels to an open Pull Request. The labels must already exist in
        the repository.

        Args:
            pr_url (str): The API URL of the Pull Request (issues endpoint) to
                send the request to
        """
        logger.info("Assigning labels to Pull Request: {}", pr_url)
        logger.info("Assigning labels: {}", self.inputs.labels)
        url = "/".join([pr_url, "labels"])
        post_request(
            url, headers=self.inputs.headers, json={"labels": self.inputs.labels}
        )

    def _assign_reviewers(self, pr_url):
        """Request reviews from GitHub users or teams on a Pull Request

        Args:
            pr_url (str): The API URL of the Pull Request (pulls endpoint) to send
                the request to
        """
        logger.info("Assigning reviewers to Pull Request: {}", pr_url)

        if self.inputs.reviewers:
            logger.info("Assigning reviewers: {}", self.inputs.reviewers)
        if self.inputs.team_reviewers:
            logger.info("Assigning team reviewers: {}", self.inputs.team_reviewers)

        url = "/".join([pr_url, "requested_reviewers"])
        post_request(
            url,
            headers=self.inputs.headers,
            json={
                "reviewers": self.inputs.reviewers,
                "team_reviewers": self.inputs.team_reviewers,
            },
        )

    def create_commit(self, commit_msg, content):
        """Create a commit over the GitHub API by creating or updating a file

        Args:
            commit_msg (str): A message describing the changes the commit applies
            content (str): The content of the file to be updated, encoded in base64
        """
        logger.info("Committing changes to file: {}", self.inputs.config_path)
        url = "/".join([self.api_url, "contents", self.inputs.config_path])
        body = {
            "message": commit_msg,
            "content": content,
            "sha": self.inputs.sha,
            "branch": self.inputs.head_branch,
        }
        put(url, json=body, headers=self.inputs.headers)

    def create_ref(self, ref, sha):
        """Create a new git reference (specifically, a branch) with GitHub's git database API
        endpoint

        Args:
            ref (str): The reference or branch name to create
            sha (str): The SHA of the parent commit to point the new reference to
        """
        logger.info("Creating new branch: {}", ref)
        url = "/".join([self.api_url, "git", "refs"])
        body = {
            "ref": f"refs/heads/{ref}",
            "sha": sha,
        }
        post_request(url, headers=self.inputs.headers, json=body)

    def create_update_pull_request(self):
        """Credate or update a Pull Request via the GitHub API"""
        url = "/".join([self.api_url, "pulls"])
        pr = {
            "title": "Bumping Docker image tags in JupyterHub config",
            "body": (
                "This Pull Request is bumping the Docker tags for the following images to the listed versions.\n\n"
                + "\n".join(
                    [
                        f"`{image}`: `{self.inputs.image_tags[image]['current']}` -> `{self.inputs.image_tags[image]['latest']}`"
                        for image in self.inputs.images_to_update
                    ]
                )
            ),
            "base": self.inputs.base_branch,
        }

        if self.pr_exists:
            logger.info("Updating Pull Request...")

            url = "/".join([url, self.pr_number])
            pr["state"] = "open"
            resp = patch_request(
                url, headers=self.inputs.headers, json=pr, return_json=True
            )

            logger.info(f"Pull Request #{resp['number']} updated!")
        else:
            logger.info("Creating Pull Request...")

            pr["head"] = self.inputs.head_branch
            resp = post_request(
                url, headers=self.inputs.headers, json=pr, return_json=True
            )

            logger.info(f"Pull Request #{resp['number']} created!")

            if self.inputs.labels:
                self._assign_labels(resp["issue_url"])

            if self.inputs.reviewers or self.inputs.team_reviewers:
                self._assign_reviewers(resp["url"])

    def find_existing_pull_request(self):
        """Check if the bot already has an open Pull Request"""
        logger.info("Finding Pull Requests previously opened...")

        url = "/".join([self.api_url, "pulls"])
        params = {"state": "open", "sort": "created", "direction": "desc"}
        resp = get_request(
            url, headers=self.inputs.headers, params=params, output="json"
        )

        head_label_exp = jmespath.compile("[*].head.label")
        matches = head_label_exp.search(resp)
        indx, match = next(
            (
                (indx, match)
                for (indx, match) in enumerate(matches)
                if self.inputs.head_branch in match
            ),
            (None, None),
        )

        if (indx is None) and (match is None):
            logger.info(
                "No relevant Pull Requests found. A new Pull Request will be opened."
            )
            random_id = "".join(random.sample(string.ascii_letters, 4))
            self.inputs.head_branch = "-".join([self.inputs.head_branch, random_id])
            self.pr_exists = False
        else:
            logger.info("Pull Request found!")
            self.inputs.head_branch = match.split(":")[-1]
            self.pr_number = resp[indx]["number"]
            self.pr_exists = True

    def get_ref(self, ref):
        """Get a git reference (specifically, a HEAD ref) using GitHub's git
        database API endpoint

        Args:
            ref (str): The reference for which to return information for

        Returns:
            dict: The JSON payload response of the request
        """
        logger.info("Pulling info for ref: {}", ref)
        url = "/".join([self.api_url, "git", "ref", "heads", ref])
        return get_request(url, headers=self.inputs.headers, output="json")
