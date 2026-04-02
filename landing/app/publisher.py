"""Publish flow manager — builds images and creates run pods for published apps."""

from __future__ import annotations

import logging

from .run_pods import RunPodManager

logger = logging.getLogger(__name__)


class Publisher:
    """Coordinates the publish flow: image naming, run pod rolling updates."""

    def __init__(self, run_pod_manager: RunPodManager) -> None:
        self._run_pods = run_pod_manager

    @staticmethod
    def get_app_image(team: str, app_slug: str) -> str:
        """Return the expected container image name for an app."""
        return f"localhost:5000/sus-app-{team}-{app_slug}:latest"

    def publish_app(self, team: str, app_slug: str) -> dict:
        """Execute the publish flow for an app.

        1. Determine the image name.
        2. Tear down any existing run pod (rolling update).
        3. Create a new run pod with the published image.

        Returns a dict with status, pod name, and image.
        """
        image = self.get_app_image(team, app_slug)

        # TODO: Trigger the actual container image build and push here.
        # For now we assume the image was already built and pushed to the
        # local registry (e.g. by a CI job or the build pod's publish step).
        logger.info("Publishing %s/%s with image %s", team, app_slug, image)

        # Rolling update — tear down the old run pod if one exists.
        existing = self._run_pods.find_run_pod(team, app_slug)
        if existing:
            logger.info(
                "Deleting existing run pod %s for rolling update", existing["name"]
            )
            self._run_pods.delete_run_pod(existing["name"])

        # Create the new run pod.
        pod_info = self._run_pods.create_run_pod(
            team=team, app_slug=app_slug, image=image
        )

        logger.info("Published %s/%s — run pod %s", team, app_slug, pod_info["name"])

        return {
            "status": "published",
            "pod_name": pod_info["name"],
            "image": image,
        }
