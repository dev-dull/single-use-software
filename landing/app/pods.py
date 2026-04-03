"""Build pod lifecycle manager — create, monitor, and tear down build pods."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from kubernetes import client, config
from kubernetes.client.rest import ApiException


class BuildPodManager:
    """Wraps the Kubernetes Python client to manage build pods."""

    def __init__(self) -> None:
        # Load cluster config (in-cluster first, fallback to kubeconfig for local dev)
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        self._core = client.CoreV1Api()
        self._namespace = os.environ.get("SUS_WORKLOADS_NAMESPACE", "sus-workloads")
        self._image = os.environ.get("SUS_BUILD_IMAGE", "sus-registry:5050/sus-build:dev")

        # Resource defaults (overridable via env)
        self._cpu_request = os.environ.get("SUS_BUILD_CPU_REQUEST", "250m")
        self._cpu_limit = os.environ.get("SUS_BUILD_CPU_LIMIT", "1")
        self._mem_request = os.environ.get("SUS_BUILD_MEM_REQUEST", "256Mi")
        self._mem_limit = os.environ.get("SUS_BUILD_MEM_LIMIT", "512Mi")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _short_hash(user_id: str, app_slug: str) -> str:
        """Return an 8-char hex hash for pod-name uniqueness."""
        digest = hashlib.sha256(f"{user_id}:{app_slug}:{datetime.now(timezone.utc).isoformat()}".encode())
        return digest.hexdigest()[:8]

    def _pod_manifest(
        self,
        name: str,
        user_id: str,
        app_slug: str,
        branch: str,
        team: str = "",
        app_name: str = "",
        app_description: str = "",
        mcp_config: dict | None = None,
    ) -> client.V1Pod:
        return client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=name,
                namespace=self._namespace,
                labels={
                    "app.kubernetes.io/component": "build",
                    "sus.dev/user": user_id,
                    "sus.dev/app": app_slug,
                },
                annotations={
                    "sus.dev/last-seen": datetime.now(timezone.utc).isoformat(),
                },
            ),
            spec=client.V1PodSpec(
                restart_policy="Never",
                containers=[
                    client.V1Container(
                        name="build",
                        image=self._image,
                        image_pull_policy=os.environ.get("SUS_BUILD_IMAGE_PULL_POLICY", "Always"),
                        ports=[
                            client.V1ContainerPort(container_port=8080, name="terminal"),
                            client.V1ContainerPort(container_port=3000, name="preview"),
                        ],
                        env=[
                            client.V1EnvVar(name="GIT_BRANCH", value=branch),
                            client.V1EnvVar(name="GIT_REPO_URL", value=os.environ.get("SUS_GIT_REPO_URL", "")),
                            client.V1EnvVar(name="USER_ID", value=user_id),
                            client.V1EnvVar(name="APP_SLUG", value=app_slug),
                            client.V1EnvVar(name="APP_TEAM", value=team),
                            client.V1EnvVar(name="APP_NAME", value=app_name),
                            client.V1EnvVar(name="APP_DESCRIPTION", value=app_description),
                            client.V1EnvVar(name="SUS_API_URL", value="http://sus-landing.sus.svc.cluster.local"),
                            client.V1EnvVar(
                                name="ANTHROPIC_API_KEY",
                                value_from=client.V1EnvVarSource(
                                    secret_key_ref=client.V1SecretKeySelector(
                                        name="sus-anthropic-api-key",
                                        key="ANTHROPIC_API_KEY",
                                        optional=True,
                                    ),
                                ),
                            ),
                            client.V1EnvVar(
                                name="GIT_TOKEN",
                                value_from=client.V1EnvVarSource(
                                    secret_key_ref=client.V1SecretKeySelector(
                                        name="sus-git-token",
                                        key="GIT_TOKEN",
                                        optional=True,
                                    ),
                                ),
                            ),
                        ]
                        + (
                            [client.V1EnvVar(name="SUS_MCP_CONFIG", value=json.dumps(mcp_config))]
                            if mcp_config
                            else []
                        ),
                        resources=client.V1ResourceRequirements(
                            requests={"cpu": self._cpu_request, "memory": self._mem_request},
                            limits={"cpu": self._cpu_limit, "memory": self._mem_limit},
                        ),
                    )
                ],
            ),
        )

    @staticmethod
    def _pod_to_dict(pod: client.V1Pod) -> dict:
        """Extract useful status info from a V1Pod object."""
        return {
            "name": pod.metadata.name,
            "phase": pod.status.phase if pod.status else None,
            "pod_ip": pod.status.pod_ip if pod.status else None,
            "ports": {
                "terminal": 8080,
                "preview": 3000,
            },
            "labels": pod.metadata.labels or {},
            "annotations": pod.metadata.annotations or {},
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_build_pod(
        self,
        user_id: str,
        app_slug: str,
        branch: str,
        team: str = "",
        app_name: str = "",
        app_description: str = "",
        mcp_config: dict | None = None,
    ) -> str:
        """Create a build pod and return its name."""
        short = self._short_hash(user_id, app_slug)
        name = f"build-{user_id}-{short}"
        manifest = self._pod_manifest(
            name, user_id, app_slug, branch,
            team=team, app_name=app_name, app_description=app_description,
            mcp_config=mcp_config,
        )
        self._core.create_namespaced_pod(namespace=self._namespace, body=manifest)
        return name

    def delete_build_pod(self, pod_name: str) -> None:
        """Delete a build pod by name."""
        try:
            self._core.delete_namespaced_pod(
                name=pod_name,
                namespace=self._namespace,
                body=client.V1DeleteOptions(grace_period_seconds=0),
            )
        except ApiException as exc:
            if exc.status != 404:
                raise

    def get_build_pod(self, pod_name: str) -> dict | None:
        """Return pod status info or None if not found."""
        try:
            pod = self._core.read_namespaced_pod(name=pod_name, namespace=self._namespace)
            return self._pod_to_dict(pod)
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise

    def list_build_pods(self, user_id: str | None = None) -> list[dict]:
        """List build pods, optionally filtered by user."""
        label_selector = "app.kubernetes.io/component=build"
        if user_id:
            label_selector += f",sus.dev/user={user_id}"

        pods = self._core.list_namespaced_pod(
            namespace=self._namespace,
            label_selector=label_selector,
        )
        return [self._pod_to_dict(p) for p in pods.items]

    def exec_in_pod(self, pod_name: str, command: list[str]) -> str:
        """Execute a command inside a build pod and return stdout."""
        from kubernetes.stream import stream
        resp = stream(
            self._core.connect_get_namespaced_pod_exec,
            name=pod_name,
            namespace=self._namespace,
            command=command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
        return resp

    def heartbeat(self, pod_name: str) -> None:
        """Update the last-seen annotation on the pod."""
        now = datetime.now(timezone.utc).isoformat()
        body = {"metadata": {"annotations": {"sus.dev/last-seen": now}}}
        self._core.patch_namespaced_pod(name=pod_name, namespace=self._namespace, body=body)

    def cleanup_idle_pods(self, timeout_minutes: int = 10) -> list[str]:
        """Delete pods whose last heartbeat is older than *timeout_minutes*. Returns deleted names."""
        now = datetime.now(timezone.utc)
        deleted: list[str] = []

        for pod_info in self.list_build_pods():
            last_seen_raw = pod_info["annotations"].get("sus.dev/last-seen")
            if not last_seen_raw:
                continue
            last_seen = datetime.fromisoformat(last_seen_raw)
            elapsed = (now - last_seen).total_seconds() / 60
            if elapsed > timeout_minutes:
                self.delete_build_pod(pod_info["name"])
                deleted.append(pod_info["name"])

        return deleted
